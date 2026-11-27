"""Create a fresh screener_auth.json by logging in to Screener.in (run this when your password
changes or the session cookie expires).

    python3 code/refresh_auth.py --username you@example.com
    (prompts for the password without echoing it; or set SCREENER_USER / SCREENER_PASSWORD)

The password is never accepted as a command-line argument (it would end up in shell history)
and is never written to disk or logged. Only the session cookies are saved, in the Playwright
storage_state format that download_screener_docs.py already reads.

Note: this only works for e-mail/password accounts. If you sign in with Google, use the
browser instead: log in, then export the cookies (e.g. Playwright `context.storage_state`).
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import List, Optional

import requests

from config import BASE_URL, DEFAULT_AUTH, LOGGER_NAME, REQUEST_TIMEOUT, USER_AGENT
from models import AuthError

log = logging.getLogger(LOGGER_NAME)

LOGIN_URL = BASE_URL + "/login/"
_CSRF_RE = re.compile(r'name=["\']csrfmiddlewaretoken["\'][^>]*value=["\']([^"\']+)["\']', re.I)


def extract_csrf(html: str) -> str:
    m = _CSRF_RE.search(html)
    if not m:
        raise AuthError("Could not find the CSRF token on the login page (did Screener change it?)")
    return m.group(1)


def login(session: requests.Session, username: str, password: str) -> None:
    """Log in; on success the session holds the `sessionid` cookie. Raises AuthError otherwise."""
    page = session.get(LOGIN_URL, timeout=REQUEST_TIMEOUT)
    token = extract_csrf(page.text)
    resp = session.post(
        LOGIN_URL,
        data={"csrfmiddlewaretoken": token, "username": username, "password": password, "next": ""},
        headers={"Referer": LOGIN_URL},
        timeout=REQUEST_TIMEOUT,
    )
    has_session = any(c.name == "sessionid" and c.value for c in session.cookies)
    if not has_session or "/login" in resp.url:
        raise AuthError("Login failed: wrong username/password, or Screener asked for a captcha / "
                        "extra verification. Try logging in once in your browser first.")


def cookies_to_storage_state(jar) -> dict:
    """Playwright storage_state shape: {"cookies": [...], "origins": []}."""
    cookies = []
    for c in jar:
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain or "www.screener.in",
            "path": c.path or "/",
            "expires": int(c.expires) if c.expires else -1,   # -1 = session cookie
            "httpOnly": bool(c.has_nonstandard_attr("HttpOnly")) if hasattr(c, "has_nonstandard_attr") else False,
            "secure": bool(c.secure),
            "sameSite": "Lax",
        })
    return {"cookies": cookies, "origins": []}


def write_auth_file(path: Path, state: dict) -> None:
    """Write the auth file (owner-only permissions); keep the previous one as <name>.json.bak."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.replace(path.with_suffix(".json.bak"))
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    path.chmod(0o600)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Log in to Screener.in and write a new screener_auth.json.")
    p.add_argument("-u", "--username", default=os.environ.get("SCREENER_USER"),
                   help="Screener login e-mail (or env SCREENER_USER)")
    p.add_argument("-o", "--out", type=Path, default=DEFAULT_AUTH, help="Where to write the auth file")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    username = args.username or input("Screener e-mail: ").strip()
    password = os.environ.get("SCREENER_PASSWORD") or getpass.getpass("Screener password (hidden): ")
    if not username or not password:
        log.error("Username and password are required")
        return 2

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    try:
        login(session, username, password)
        # Visit a logged-in page once so the final cookie jar is exactly what the browser would hold.
        session.get(BASE_URL + "/", timeout=REQUEST_TIMEOUT)
    except AuthError as exc:
        log.error("%s", exc)
        return 2
    except requests.RequestException as exc:
        log.error("Network error while logging in: %s", exc)
        return 2

    write_auth_file(args.out, cookies_to_storage_state(session.cookies))
    log.info("Saved new session to %s (previous file kept as .bak). Do not share or commit it.", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
