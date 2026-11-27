"""Build an authenticated requests.Session from screener_auth.json."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List

import requests

from config import LOGGER_NAME, USER_AGENT
from models import AuthError

log = logging.getLogger(LOGGER_NAME)


def load_cookies(auth_path: Path) -> List[dict]:
    """Accept Playwright storage_state ({"cookies": [...]}), a bare list, or {name: value}."""
    if not auth_path.is_file():
        raise AuthError(f"Auth file not found: {auth_path} (see screener_auth.example.json)")
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError(f"Auth file is not valid JSON: {exc}") from exc

    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        raw = data["cookies"]
    elif isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = [{"name": k, "value": v} for k, v in data.items() if isinstance(v, str)]
    else:
        raw = []

    cookies = [c for c in raw if isinstance(c, dict) and c.get("name") and c.get("value")]
    if not any(c["name"] == "sessionid" for c in cookies):
        raise AuthError("No 'sessionid' cookie found in auth file")
    return cookies


def build_session(auth_path: Path) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    now = time.time()
    for c in load_cookies(auth_path):
        expires = c.get("expires")
        if isinstance(expires, (int, float)) and 0 < expires < now:
            log.warning("Cookie '%s' has expired; re-export your session", c["name"])
        session.cookies.set(c["name"], c["value"],
                            domain=c.get("domain") or "www.screener.in",
                            path=c.get("path") or "/")
    return session
