"""Download a single document to disk (atomic, content-validated)."""
from __future__ import annotations

from pathlib import Path
from typing import Set
from urllib.parse import urlparse

import requests

from config import ALLOWED_EXTENSIONS, BASE_URL
from http_client import Fetcher
from models import Doc


def url_extension(url: str) -> str:
    """File extension from the URL path; defaults to .pdf (e.g. BSE AnnPdfOpen.aspx links)."""
    ext = Path(urlparse(url).path).suffix.lower()
    return ext if ext in ALLOWED_EXTENSIONS else ".pdf"


def pick_filename(doc: Doc, claimed: Set[str]) -> str:
    """Return a filename not claimed by another URL (adds _2, _3 ... on collisions)."""
    ext = url_extension(doc.url)
    n = 1
    while True:
        name = f"{doc.base_name}{'' if n == 1 else f'_{n}'}{ext}"
        if name not in claimed:
            return name
        n += 1


def download_file(fetcher: Fetcher, url: str, dest: Path) -> None:
    headers = {"Referer": BASE_URL + "/"} if url.startswith(BASE_URL) else {}
    resp = fetcher.get(url, headers=headers, stream=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        if resp.status_code != 200:
            raise requests.HTTPError(f"HTTP {resp.status_code}")
        check_pdf = dest.suffix == ".pdf"
        first = True
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if first:
                    first = False
                    if check_pdf and b"%PDF" not in chunk[:1024]:
                        raise ValueError(
                            f"not a PDF (content-type={resp.headers.get('Content-Type')})")
                fh.write(chunk)
        if first:
            raise ValueError("empty response")
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        resp.close()
