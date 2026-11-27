"""Small filesystem / string helpers."""
from __future__ import annotations

import re
from datetime import datetime, timezone


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", name.strip())
    return re.sub(r"_+", "_", name).strip("_") or "document"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
