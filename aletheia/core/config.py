"""Configuration: YAML file + environment overrides. No secrets are ever written to disk."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel

DEFAULTS: Dict[str, Any] = {
    "llm": {
        # Order matters: the first backend that initialises is used; the rest are fallbacks.
        "backends": ["callable", "anthropic", "openai", "ollama", "replay", "rules"],
        "model": None,              # resolved per backend
        "max_tokens": 2000,
        "cache_dir": "cache/llm",
        "record": True,             # write every response to the replay cache
        "offline": False,           # if true, only replay + rules are allowed
    },
    "tools": {
        "cache_dir": "cache/tools",
        "use_cache": True,
        "network": True,
        "timeout_s": 60,
        "vina_bin": "tools/vina/vina_1.2.7_win.exe",
    },
    "run": {"run_dir": "runs", "echo": False, "seed": 20261111},
    "orchestrator": {"pattern": "supervisor", "max_parallel": 4, "budget_s": 900},
    "verifier": {"strict_citation": True, "allow_global_pool": True, "block_on_violation": True},
    # redock_exhaustiveness is deliberately higher than the screening setting: the redocking
    # check must measure whether the receptor+box can reproduce a known pose, not whether a cheap
    # search happens to find it.
    "docking": {"exhaustiveness": 8, "redock_exhaustiveness": 24, "num_modes": 9, "seed": 42,
                "box_pad": 5.0},
    # Ablation switches, used only by the evaluation harness to measure what each component buys.
    "ablation": {"no_critic": False, "single_generator": False, "no_guardrail": False,
                 "no_verifier": False},
}


def _deep_update(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    import copy
    cfg = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("ALETHEIA_CONFIG") or "config/default.yaml"
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            _deep_update(cfg, yaml.safe_load(fh) or {})
    if os.environ.get("ALETHEIA_OFFLINE", "").lower() in ("1", "true", "yes"):
        cfg["llm"]["offline"] = True
        cfg["tools"]["network"] = False
    _deep_update(cfg, overrides)
    return cfg
