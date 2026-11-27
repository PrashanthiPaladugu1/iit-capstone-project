"""Test support: puts code/ on sys.path and provides fakes. Import this first in every test."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

CODE_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", content: Optional[bytes] = None,
                 url: str = "", headers: Optional[dict] = None):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode()
        self.url = url
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size: int = 1024):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeFetcher:
    """Stands in for http_client.Fetcher. routes: {(METHOD, url): FakeResponse | Exception}."""

    def __init__(self, routes: Optional[Dict[tuple, object]] = None):
        self.routes = routes or {}
        self.calls: List[tuple] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        result = self.routes.get((method, url))
        if result is None:
            return FakeResponse(404, url=url)
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def urls(self, method: str = "GET") -> List[str]:
        return [u for m, u, _ in self.calls if m == method]


PDF_BYTES = b"%PDF-1.4\n" + b"x" * 100
XLSX_BYTES = b"PK\x03\x04" + b"y" * 100
