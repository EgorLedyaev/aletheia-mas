"""Tool registry: typed, versioned, cached, timed, and auditable.

Agents never call a library directly -- they call `ctx.tools.call("rdkit.descriptors", ...)`.
That indirection is what makes the trace assertions in the evaluation harness possible
(right tools, right order) and what guarantees every tool run lands in the audit log.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .provenance import ToolCallRecord, params_hash, utcnow


def _code_hash(fn: Callable[..., Any]) -> str:
    """Hash of a tool's own source, so changing an implementation invalidates its cache.

    Without this, fixing a bug in a tool leaves every previously cached result in place and the
    system keeps serving pre-fix numbers -- which is exactly the kind of silent staleness a
    provenance system must not have. The hash is part of the cache key and of the recorded
    params_hash, so a claim's provenance names the implementation that produced it.
    """
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        src = getattr(fn, "__qualname__", repr(fn))
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:8]


@dataclass
class ToolSpec:
    name: str
    version: str
    func: Callable[..., Dict[str, Any]]
    description: str = ""
    default_tag: str = "COMPUTED"
    license: str = "unknown"
    network: bool = False
    cacheable: bool = True
    schema: Dict[str, Any] = field(default_factory=dict)
    cost_hint: str = "cheap"          # cheap | medium | expensive -- used by the funnel gates


class ToolError(RuntimeError):
    pass


@dataclass
class ToolResult:
    tool: str
    version: str
    call_id: str
    params: Dict[str, Any]
    params_hash: str
    data: Dict[str, Any]
    ok: bool = True
    error: Optional[str] = None
    cached: bool = False
    duration_s: float = 0.0

    def __bool__(self) -> bool:
        return self.ok

    def get(self, key: str, default: Any = None) -> Any:
        return (self.data or {}).get(key, default)


class ToolRegistry:
    def __init__(self, config: Optional[Dict[str, Any]] = None, tracer: Any = None):
        cfg = (config or {}).get("tools", {}) if config else {}
        self.specs: Dict[str, ToolSpec] = {}
        self.cache_dir = cfg.get("cache_dir", "cache/tools")
        self.use_cache = bool(cfg.get("use_cache", True))
        self.network = bool(cfg.get("network", True))
        self.config = config or {}
        self.tracer = tracer
        self.history: List[ToolCallRecord] = []
        os.makedirs(self.cache_dir, exist_ok=True)

    # -- registration --------------------------------------------------------
    def register(self, spec: ToolSpec) -> ToolSpec:
        self.specs[spec.name] = spec
        return spec

    def tool(self, name: str, version: str, **kw: Any) -> Callable:
        def deco(fn: Callable[..., Dict[str, Any]]) -> Callable:
            self.register(ToolSpec(name=name, version=version, func=fn,
                                   description=(fn.__doc__ or "").strip().split("\n")[0], **kw))
            return fn
        return deco

    def names(self) -> List[str]:
        return sorted(self.specs)

    def describe(self) -> List[Dict[str, Any]]:
        return [{"name": s.name, "version": s.version, "description": s.description,
                 "license": s.license, "network": s.network, "tag": s.default_tag,
                 "cost": s.cost_hint, "schema": s.schema} for s in self.specs.values()]

    # -- caching -------------------------------------------------------------
    def _cache_path(self, spec: ToolSpec, ph: str) -> str:
        d = os.path.join(self.cache_dir, spec.name.replace(".", "_"))
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{spec.version}_{ph}.json")

    # -- invocation ----------------------------------------------------------
    def call(self, tool: str, /, agent: Optional[str] = None, _no_cache: bool = False,
             **params: Any) -> ToolResult:
        """Invoke a registered tool. `tool` is positional-only so that a parameter called
        `name` (PubChem, ChEMBL search) cannot collide with it."""
        name = tool
        spec = self.specs.get(name)
        call_id = f"C-{uuid.uuid4().hex[:8]}"
        if spec is None:
            raise ToolError(f"tool '{name}' is not registered; available: {self.names()}")
        code = _code_hash(spec.func)
        ph = params_hash({"tool": name, "version": spec.version, "code": code, **params})
        started = utcnow()
        t0 = time.time()

        if spec.network and not self.network:
            res = ToolResult(tool=name, version=spec.version, call_id=call_id, params=params,
                             params_hash=ph, data={}, ok=False,
                             error="network disabled (offline mode) and no cached result")
            cp = self._cache_path(spec, ph)
            if os.path.exists(cp):
                with open(cp, "r", encoding="utf-8") as fh:
                    res = ToolResult(tool=name, version=spec.version, call_id=call_id,
                                     params=params, params_hash=ph, data=json.load(fh)["data"],
                                     cached=True)
            self._finish(res, spec, started, t0, agent)
            return res

        if self.use_cache and spec.cacheable and not _no_cache:
            cp = self._cache_path(spec, ph)
            if os.path.exists(cp):
                try:
                    with open(cp, "r", encoding="utf-8") as fh:
                        payload = json.load(fh)
                    res = ToolResult(tool=name, version=spec.version, call_id=call_id,
                                     params=params, params_hash=ph, data=payload["data"],
                                     cached=True)
                    self._finish(res, spec, started, t0, agent)
                    return res
                except (OSError, KeyError, json.JSONDecodeError):
                    pass

        try:
            data = spec.func(**params)
            if not isinstance(data, dict):
                data = {"value": data}
            res = ToolResult(tool=name, version=spec.version, call_id=call_id, params=params,
                             params_hash=ph, data=data)
            if self.use_cache and spec.cacheable:
                # Atomic write: a partially written cache file is indistinguishable from a valid
                # one to the next reader, and two runs can touch the same key concurrently.
                cp = self._cache_path(spec, ph)
                try:
                    tmp = f"{cp}.{os.getpid()}.tmp"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        json.dump({"tool": name, "version": spec.version, "params": params,
                                   "params_hash": ph, "cached_at": utcnow(), "data": data},
                                  fh, indent=1, default=str)
                    os.replace(tmp, cp)
                except OSError:
                    pass
        except Exception as exc:
            res = ToolResult(tool=name, version=spec.version, call_id=call_id, params=params,
                             params_hash=ph, data={}, ok=False,
                             error=f"{type(exc).__name__}: {exc}"[:400])
        self._finish(res, spec, started, t0, agent)
        return res

    def _finish(self, res: ToolResult, spec: ToolSpec, started: str, t0: float,
                agent: Optional[str]) -> None:
        res.duration_s = round(time.time() - t0, 3)
        rec = ToolCallRecord(call_id=res.call_id, tool=res.tool, tool_version=res.version,
                             params={k: _short(v) for k, v in res.params.items()},
                             params_hash=res.params_hash, started_at=started,
                             duration_s=res.duration_s, cached=res.cached, ok=res.ok,
                             error=res.error, agent=agent)
        self.history.append(rec)
        if self.tracer:
            self.tracer.emit("tool_call", tool=res.tool, version=res.version, agent=agent,
                             call_id=res.call_id, cached=res.cached, ok=res.ok,
                             duration_s=res.duration_s, params_hash=res.params_hash,
                             error=res.error)


def _short(v: Any, n: int = 200) -> Any:
    s = v if isinstance(v, (int, float, bool, type(None))) else str(v)
    return s[:n] + "..." if isinstance(s, str) and len(s) > n else s
