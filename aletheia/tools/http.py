"""Thin HTTP helper: plain user agent, explicit timeouts, no retries-on-policy-blocks."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import requests

UA = "Aletheia-MAS/0.9 (research prototype; chemistry/biology data access)"
_SESSION: Optional[requests.Session] = None


def session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({"User-Agent": UA, "Accept": "application/json"})
    return _SESSION


def get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60,
             tries: int = 2) -> Dict[str, Any]:
    last = None
    for i in range(tries):
        r = session().get(url, params=params, timeout=timeout)
        if r.status_code == 404:
            raise FileNotFoundError(f"404 at {r.url}")
        if r.status_code in (429, 503) and i + 1 < tries:
            time.sleep(1.5 * (i + 1))
            last = r
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} at {r.url}: {r.text[:200]}")
        try:
            return r.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"non-JSON response from {r.url}: {exc}")
    raise RuntimeError(f"HTTP {last.status_code if last else '?'} after {tries} tries at {url}")


def get_text(url: str, timeout: int = 60) -> str:
    r = session().get(url, timeout=timeout, headers={"Accept": "text/plain"})
    if r.status_code == 404:
        raise FileNotFoundError(f"404 at {r.url}")
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} at {r.url}: {r.text[:200]}")
    return r.text
