"""Replicate the 'Export to Excel' button on a Screener company page."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import BASE_URL
from http_client import Fetcher


def export_excel(fetcher: Fetcher, page_url: str, html: str, dest: Path) -> None:
    """POST the export form (with its CSRF token) and save the returned .xlsx."""
    soup = BeautifulSoup(html, "html.parser")
    button = soup.find("button", attrs={"aria-label": "Export to Excel"})
    form = button.find_parent("form") if button else None
    if button is None or form is None or not button.get("formaction"):
        raise ValueError("'Export to Excel' button not found (not logged in, or no premium access?)")

    data = {i["name"]: i.get("value", "") for i in form.find_all("input", attrs={"name": True})}
    resp = fetcher.request("POST", urljoin(BASE_URL, button["formaction"]), data=data,
                           headers={"Referer": page_url})
    try:
        if resp.status_code != 200:
            raise requests.HTTPError(f"HTTP {resp.status_code}")
        if not resp.content.startswith(b"PK"):  # .xlsx is a zip container
            raise ValueError(f"not an xlsx (content-type={resp.headers.get('Content-Type')})")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(resp.content)
        tmp.replace(dest)  # atomic overwrite: the export is a snapshot, refreshed every run
    finally:
        resp.close()
