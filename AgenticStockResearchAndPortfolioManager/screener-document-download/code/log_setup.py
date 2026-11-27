"""Logging configuration."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def default_log_path(log_dir: Path, now: Optional[datetime] = None) -> Path:
    """logs/run_YYYYMMDD_HHMMSS.log - one file per run."""
    now = now or datetime.now()
    return log_dir / f"run_{now:%Y%m%d_%H%M%S}.log"


def setup_logging(verbose: bool, log_file: Optional[Path]) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
                        force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
