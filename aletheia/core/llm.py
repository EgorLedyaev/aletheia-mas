"""Provider-agnostic LLM layer.

Backends, tried in configured order:
  callable   an injected python callable (used when Aletheia runs inside a host kernel/SDK)
  anthropic  Anthropic Messages API           (env ANTHROPIC_API_KEY)
  openai     any OpenAI-compatible server     (env OPENAI_API_KEY, OPENAI_BASE_URL)
  ollama     local open-weights server        (env OLLAMA_HOST, default 127.0.0.1:11434)
  replay     on-disk cache of previous responses -- the offline demo path
  rules      no LLM at all; callers must supply a deterministic fallback

Every live response is written to the replay cache keyed by a hash of the exact request, so a
venue with no internet and no API key still reproduces the recorded agent behaviour instead of
silently changing it. `LLMResponse.cached` and `.backend` are surfaced in the run trace.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str = ""
    tool_use: Optional[Dict[str, Any]] = None
    backend: str = "none"
    model: Optional[str] = None
    cached: bool = False
    usage: Dict[str, Any] = {}
    error: Optional[str] = None


def request_key(payload: Dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Backend:
    name = "base"

    def available(self) -> bool:
        return False

    def complete(self, messages: List[Dict[str, Any]], system: Optional[str],
                 tools: Optional[List[Dict[str, Any]]], tool_choice: Optional[Dict[str, Any]],
                 max_tokens: int, model: Optional[str]) -> LLMResponse:
        raise NotImplementedError


class CallableBackend(Backend):
    """Wraps an injected callable with the host-SDK signature (prompt/messages/tools -> dict)."""
    name = "callable"

    def __init__(self, fn: Optional[Callable[..., Any]] = None, model: Optional[str] = None):
        self.fn = fn or _INJECTED.get("fn")
        self.model = model or _INJECTED.get("model")
        self.extra = dict(_INJECTED.get("extra") or {})

    def available(self) -> bool:
        return callable(self.fn)

    def complete(self, messages, system, tools, tool_choice, max_tokens, model):
        req: Dict[str, Any] = {"messages": messages, "max_tokens": max_tokens}
        if system:
            req["system"] = system
        if tools:
            req["tools"] = tools
        if tool_choice:
            req["tool_choice"] = tool_choice
        mdl = model or self.model
        if mdl:
            req["model"] = mdl
        req.update(self.extra)
        out = self.fn(**req)
        if isinstance(out, list):
            out = out[0]
        if not isinstance(out, dict):
            out = {"text": str(out)}
        if out.get("error"):
            return LLMResponse(backend=self.name, error=str(out["error"]))
        return LLMResponse(text=out.get("text", "") or "", tool_use=out.get("tool_use"),
                           backend=self.name, model=out.get("model") or mdl,
                           usage=out.get("usage") or {})


_INJECTED: Dict[str, Any] = {}


def inject_callable(fn: Callable[..., Any], model: Optional[str] = None,
                    **extra: Any) -> None:
    """Register a host-provided LLM callable (e.g. a notebook SDK) as the `callable` backend.

    `extra` is forwarded verbatim on every call (used to pin e.g. thinking off).
    """
    _INJECTED["fn"] = fn
    _INJECTED["model"] = model
    _INJECTED["extra"] = extra


class AnthropicBackend(Backend):
    name = "anthropic"
    DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "anthropic-sonnet-4-5")

    def available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def complete(self, messages, system, tools, tool_choice, max_tokens, model):
        import requests
        body: Dict[str, Any] = {"model": model or self.DEFAULT_MODEL,
                                "max_tokens": max_tokens, "messages": messages}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        r = requests.post("https://api.anthropic.com/v1/messages", json=body, timeout=120,
                          headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                                   "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"})
        if r.status_code >= 400:
            return LLMResponse(backend=self.name, error=f"HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        tu = next((b for b in d.get("content", []) if b.get("type") == "tool_use"), None)
        return LLMResponse(text=text, backend=self.name, model=d.get("model"),
                           tool_use={"name": tu["name"], "input": tu["input"]} if tu else None,
                           usage=d.get("usage") or {})


class OpenAICompatibleBackend(Backend):
    """Any /v1/chat/completions server: OpenAI, vLLM, LM Studio, OpenRouter, local gateways."""
    name = "openai"

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_BASE_URL"))

    def complete(self, messages, system, tools, tool_choice, max_tokens, model):
        import requests
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str)
             else json.dumps(m["content"])} for m in messages]
        body: Dict[str, Any] = {"model": model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                                "messages": msgs, "max_tokens": max_tokens}
        if tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": t["name"], "description": t.get("description", ""),
                                           "parameters": t["input_schema"]}} for t in tools]
            if tool_choice and tool_choice.get("name"):
                body["tool_choice"] = {"type": "function",
                                       "function": {"name": tool_choice["name"]}}
        headers = {"content-type": "application/json"}
        if os.environ.get("OPENAI_API_KEY"):
            headers["authorization"] = "Bearer " + os.environ["OPENAI_API_KEY"]
        r = requests.post(base + "/chat/completions", json=body, headers=headers, timeout=120)
        if r.status_code >= 400:
            return LLMResponse(backend=self.name, error=f"HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        ch = (d.get("choices") or [{}])[0].get("message", {})
        tu = None
        if ch.get("tool_calls"):
            c = ch["tool_calls"][0]["function"]
            try:
                tu = {"name": c["name"], "input": json.loads(c.get("arguments") or "{}")}
            except json.JSONDecodeError:
                tu = {"name": c["name"], "input": {}}
        return LLMResponse(text=ch.get("content") or "", tool_use=tu, backend=self.name,
                           model=d.get("model"), usage=d.get("usage") or {})


class OllamaBackend(Backend):
    """Local open-weights fallback. Default model is small enough for a laptop CPU."""
    name = "ollama"
    DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")

    def _host(self) -> str:
        return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

    def available(self) -> bool:
        import requests
        try:
            return requests.get(self._host() + "/api/tags", timeout=2).status_code == 200
        except Exception:
            return False

    def complete(self, messages, system, tools, tool_choice, max_tokens, model):
        import requests
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str)
             else json.dumps(m["content"])} for m in messages]
        body = {"model": model or self.DEFAULT_MODEL, "messages": msgs, "stream": False,
                "options": {"num_predict": max_tokens}}
        if tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": t["name"], "description": t.get("description", ""),
                                           "parameters": t["input_schema"]}} for t in tools]
        r = requests.post(self._host() + "/api/chat", json=body, timeout=600)
        if r.status_code >= 400:
            return LLMResponse(backend=self.name, error=f"HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        msg = d.get("message", {})
        tu = None
        if msg.get("tool_calls"):
            f = msg["tool_calls"][0]["function"]
            args = f.get("arguments")
            tu = {"name": f.get("name"), "input": args if isinstance(args, dict) else json.loads(args or "{}")}
        return LLMResponse(text=msg.get("content") or "", tool_use=tu, backend=self.name,
                           model=d.get("model"), usage={"eval_count": d.get("eval_count")})


class RulesBackend(Backend):
    """Explicitly no LLM. Callers must pass a deterministic fallback; see LLMClient.structured."""
    name = "rules"

    def available(self) -> bool:
        return True

    def complete(self, messages, system, tools, tool_choice, max_tokens, model):
        return LLMResponse(backend=self.name, error="no-llm-backend: deterministic fallback required")


BACKENDS = {b.name: b for b in [CallableBackend, AnthropicBackend, OpenAICompatibleBackend,
                                OllamaBackend, RulesBackend]}


class LLMClient:
    """Chooses a backend, caches every response, and exposes a structured-output helper."""

    def __init__(self, config: Dict[str, Any], tracer: Any = None):
        self.cfg = config.get("llm", config)
        self.tracer = tracer
        self.cache_dir = self.cfg.get("cache_dir", "cache/llm")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.offline = bool(self.cfg.get("offline"))
        self.record = bool(self.cfg.get("record", True))
        self.max_tokens = int(self.cfg.get("max_tokens", 2000))
        self.model = self.cfg.get("model")
        self.calls: List[Dict[str, Any]] = []
        order = list(self.cfg.get("backends", ["callable", "anthropic", "openai", "ollama", "replay", "rules"]))
        if self.offline:
            order = [b for b in order if b in ("replay", "rules")]
        self.order = order
        self._resolved: Optional[Backend] = None

    # -- backend selection ---------------------------------------------------
    def _pick(self) -> Optional[Backend]:
        if self._resolved is not None:
            return self._resolved
        for name in self.order:
            if name == "replay":
                continue
            cls = BACKENDS.get(name)
            if cls is None:
                continue
            try:
                b = cls()
            except Exception:
                continue
            if b.available():
                self._resolved = b
                return b
        return None

    @property
    def backend_name(self) -> str:
        if self.offline:
            return "replay/rules (offline)"
        b = self._pick()
        return b.name if b else "replay/rules"

    # -- cache ---------------------------------------------------------------
    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, key + ".json")

    def _read_cache(self, key: str) -> Optional[LLMResponse]:
        p = self._cache_path(key)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                r = LLMResponse(**d["response"])
                r.cached = True
                return r
            except Exception:
                return None
        return None

    def _write_cache(self, key: str, payload: Dict[str, Any], resp: LLMResponse) -> None:
        path = self._cache_path(key)
        try:
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"key": key, "request": payload,
                           "response": resp.model_dump()}, fh, indent=1, default=str)
            os.replace(tmp, path)       # atomic: never leave a half-written cache entry
        except OSError:
            pass

    # -- main call -----------------------------------------------------------
    def complete(self, prompt: Optional[str] = None, *, system: Optional[str] = None,
                 messages: Optional[List[Dict[str, Any]]] = None,
                 tools: Optional[List[Dict[str, Any]]] = None,
                 tool_choice: Optional[Dict[str, Any]] = None,
                 max_tokens: Optional[int] = None, model: Optional[str] = None,
                 purpose: str = "") -> LLMResponse:
        messages = messages or [{"role": "user", "content": prompt or ""}]
        max_tokens = max_tokens or self.max_tokens
        payload = {"messages": messages, "system": system, "tools": tools,
                   "tool_choice": tool_choice, "max_tokens": max_tokens,
                   "model": model or self.model, "purpose": purpose}
        key = request_key(payload)
        cached = self._read_cache(key)
        if cached is not None and (self.offline or self.cfg.get("prefer_cache", True)):
            self._log(purpose, cached, key, 0.0)
            return cached
        b = self._pick()
        if b is None:
            r = LLMResponse(backend="rules", error="no LLM backend available and no cached response")
            self._log(purpose, r, key, 0.0)
            return r
        t0 = time.time()
        try:
            resp = b.complete(messages, system, tools, tool_choice, max_tokens, model or self.model)
        except Exception as exc:
            resp = LLMResponse(backend=b.name, error=f"{type(exc).__name__}: {exc}"[:300])
        dt = time.time() - t0
        if self.record and not resp.error:
            self._write_cache(key, payload, resp)
        self._log(purpose, resp, key, dt)
        return resp

    def _log(self, purpose: str, resp: LLMResponse, key: str, dt: float) -> None:
        rec = {"purpose": purpose, "backend": resp.backend, "cached": resp.cached,
               "key": key[:12], "duration_s": round(dt, 3), "error": resp.error,
               "usage": resp.usage}
        self.calls.append(rec)
        if self.tracer:
            self.tracer.emit("llm_call", **rec)

    # -- structured output ---------------------------------------------------
    def structured(self, prompt: str, schema: Dict[str, Any], *, system: Optional[str] = None,
                   deterministic: Optional[Callable[[], Dict[str, Any]]] = None,
                   purpose: str = "", max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Force a tool-shaped JSON answer. Falls back to `deterministic()` on any failure.

        Returns {"data": ..., "backend": ..., "cached": ..., "fallback": bool}.
        """
        tool = {"name": schema["name"], "description": schema.get("description", ""),
                "input_schema": schema["input_schema"]}
        resp = self.complete(prompt, system=system, tools=[tool],
                             tool_choice={"type": "tool", "name": schema["name"]},
                             purpose=purpose, max_tokens=max_tokens)
        data = (resp.tool_use or {}).get("input") if resp.tool_use else None
        if data is None and resp.text:
            data = _loads_json_block(resp.text)
        if data is None:
            if deterministic is None:
                return {"data": None, "backend": resp.backend, "cached": resp.cached,
                        "fallback": False, "error": resp.error or "no structured output"}
            return {"data": deterministic(), "backend": "rules", "cached": False,
                    "fallback": True, "error": resp.error}
        return {"data": data, "backend": resp.backend, "cached": resp.cached, "fallback": False}


def _loads_json_block(text: str) -> Optional[Dict[str, Any]]:
    import re
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None
