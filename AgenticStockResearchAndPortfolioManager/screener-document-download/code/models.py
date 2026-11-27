"""Shared data types."""
from __future__ import annotations

from dataclasses import dataclass

from fs_utils import sanitize_filename


class AuthError(Exception):
    """Raised when the Screener session is missing, expired or rejected."""


@dataclass(frozen=True)
class Doc:
    kind: str   # "Annual_Report" | "Transcript" | "PPT"
    label: str  # "2026" or "Nov_2026"
    url: str

    @property
    def base_name(self) -> str:
        return sanitize_filename(f"{self.kind}_{self.label}")
