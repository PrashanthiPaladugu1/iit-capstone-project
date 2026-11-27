"""Per-symbol workflow: fetch page -> export Excel -> download new documents."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, Optional, Set

from config import COMPANY_URL, LOGGER_NAME
from excel_export import export_excel
from file_downloader import download_file, pick_filename
from fs_utils import now_iso, sanitize_filename
from history import History, record_entry, symbol_history
from html_parser import parse_documents
from http_client import Fetcher
from models import AuthError

log = logging.getLogger(LOGGER_NAME)


def process_symbol(symbol: str, fetcher: Fetcher, history: History, out_dir: Path,
                   history_path: Path, kinds: Set[str], dry_run: bool,
                   excel: bool = True, standalone: bool = False,
                   stop: Optional[threading.Event] = None) -> Dict[str, int]:
    """Runs one stock sequentially from start to finish (page, Excel, then each document).
    `stop` lets the caller end the run early; it is only checked between steps."""
    stats = {"new": 0, "skipped": 0, "failed": 0}
    key = symbol.upper()
    if stop is not None and stop.is_set():
        return stats
    url = COMPANY_URL.format(symbol=key, view="" if standalone else "consolidated/")
    log.info("[%s] Fetching %s", key, url)

    resp = fetcher.get(url)
    if resp.status_code == 404:
        log.error("[%s] Company page not found (404)", key)
        stats["failed"] += 1
        return stats
    if "/login" in resp.url:
        raise AuthError("Redirected to login page - session cookie is invalid or expired")
    if resp.status_code != 200:
        log.error("[%s] Unexpected HTTP %d", key, resp.status_code)
        stats["failed"] += 1
        return stats

    sym_hist = symbol_history(history, key)
    sym_dir = out_dir / key  # data/{SYMBOL}/

    if excel:
        xlsx_name = f"Financials_{sanitize_filename(key)}.xlsx"
        if dry_run:
            log.info("[%s] [dry-run] would export %s", key, xlsx_name)
            stats["new"] += 1
        else:
            try:
                export_excel(fetcher, resp.url, resp.text, sym_dir / xlsx_name)
                size_kb = (sym_dir / xlsx_name).stat().st_size / 1024
                log.info("[%s] Exported %s (%.0f KB)", key, xlsx_name, size_kb)
                record_entry(history, history_path, key, "__excel__",
                             {"file": xlsx_name, "type": "Excel", "downloaded_at": now_iso()})
                stats["new"] += 1
            except Exception as exc:
                log.error("[%s] Excel export failed: %s", key, exc)
                stats["failed"] += 1

    docs = [d for d in parse_documents(resp.text) if d.kind in kinds]
    if not docs:
        log.warning("[%s] No documents found in #documents section", key)
        return stats
    log.info("[%s] Found %d candidate documents", key, len(docs))

    claimed: Set[str] = {rec["file"] for rec in sym_hist.values() if "file" in rec}

    for doc in docs:
        if stop is not None and stop.is_set():
            log.info("[%s] Stop requested; leaving the remaining documents for the next run", key)
            break
        if doc.url in sym_hist:
            stats["skipped"] += 1
            log.debug("[%s] Already in history: %s", key, doc.url)
            continue

        filename = pick_filename(doc, claimed)
        dest = sym_dir / filename
        claimed.add(filename)

        record = {"file": filename, "type": doc.kind, "label": doc.label}
        if dest.exists() and dest.stat().st_size > 0:
            # Present on disk but missing from history (e.g. history was deleted): adopt it.
            log.info("[%s] Already on disk, recording: %s", key, filename)
            record_entry(history, history_path, key, doc.url,
                         {**record, "downloaded_at": now_iso(), "adopted": True})
            stats["skipped"] += 1
            continue

        if dry_run:
            log.info("[%s] [dry-run] would download %s <- %s", key, filename, doc.url)
            stats["new"] += 1
            continue

        try:
            sym_dir.mkdir(parents=True, exist_ok=True)
            download_file(fetcher, doc.url, dest)
        except Exception as exc:  # keep going; failed docs are retried next run
            log.error("[%s] Failed %s (%s): %s", key, filename, doc.url, exc)
            claimed.discard(filename)
            stats["failed"] += 1
            continue

        size_kb = dest.stat().st_size / 1024
        log.info("[%s] Downloaded %s (%.0f KB)", key, filename, size_kb)
        record_entry(history, history_path, key, doc.url,
                     {**record, "downloaded_at": now_iso()})  # persisted after every file
        stats["new"] += 1

    return stats
