"""Download the constituents of every NSE index into data_nse_index/<YYYYMMDD>/.

    python3 code/nse_indices.py             # today's run; indices already saved today are skipped
    python3 code/nse_indices.py --force     # download everything again

Output per run day: one CSV per index (e.g. NIFTY_50.csv) plus NSE_ALL_INDICES_<timestamp>.csv
(the master list with the index-level numbers). Ported from the NSE_ALL_INDEX.ipynb Colab notebook,
but it uses plain `requests` (NSE's JSON API answers without a browser), so no Chrome/Selenium is needed.

Column fix versus the notebook: its `high`, `low`, `ltP` and `ptsC30d` columns were always "-" because it
read keys NSE does not send. NSE's real keys are dayHigh, dayLow, lastPrice and perChange30d.
"""
from __future__ import annotations

import argparse
import csv
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

from config import DEFAULT_LOG_DIR, LOGGER_NAME, PROJECT_ROOT, USER_AGENT
from log_setup import setup_logging

log = logging.getLogger(LOGGER_NAME)

HOME_URL = "https://www.nseindia.com/"
INDICES_URL = "https://www.nseindia.com/api/allIndices"
INDEX_URL = "https://www.nseindia.com/api/equity-stock-indices"
DEFAULT_OUT = PROJECT_ROOT / "data_nse_index"

MAX_RETRIES = 3
TIMEOUT = 30
MIN_DELAY, MAX_DELAY = 1.0, 2.0  # polite pause between index requests

HEADER = ["symbol", "open", "high", "low", "ltP", "ptsC30d", "volume", "value_crores", "yHigh", "yLow", "pChange"]
# CSV column -> key in NSE's JSON (same column names as the notebook)
SOURCE_KEYS = ["symbol", "open", "dayHigh", "dayLow", "lastPrice", "perChange30d",
               "totalTradedVolume", "totalTradedValue", "yearHigh", "yearLow", "pChange"]

Sleep = Callable[[float], None]


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": HOME_URL,
    })
    return s


def _prime(session: requests.Session) -> None:
    """Visit the home page so NSE hands out its cookies. Failure here is not fatal."""
    try:
        session.get(HOME_URL, timeout=TIMEOUT)
    except requests.RequestException as exc:
        log.debug("Priming NSE session failed: %s", exc)


def _get_json(session: requests.Session, url: str, params: Optional[dict], sleep: Sleep) -> dict:
    last = "unknown error"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "data" in data:
                    return data
                last = "response has no 'data'"
            else:
                last = f"HTTP {resp.status_code}"
        except ValueError:
            last = "response was not JSON (likely blocked)"
        except requests.RequestException as exc:
            last = str(exc)
        log.warning("Attempt %d/%d failed for %s %s: %s", attempt, MAX_RETRIES, url, params or "", last)
        if attempt < MAX_RETRIES:
            sleep(2 ** attempt)
            _prime(session)  # cookies may have expired
    raise RuntimeError(f"Giving up on {url} {params or ''}: {last}")


def list_indices(session: requests.Session, sleep: Sleep = time.sleep) -> Tuple[List[Tuple[str, str]], List[dict]]:
    """([(display name, name to request)], raw rows of the master list).

    NSE's constituents endpoint wants the short `indexSymbol` (e.g. "NIFTY FIN SERVICE"), not the
    display name ("NIFTY FINANCIAL SERVICES"); with the display name it returns HTTP 200 and no rows
    for most indices. Files are still named after the display name.
    """
    _prime(session)
    rows = _get_json(session, INDICES_URL, None, sleep)["data"]
    targets = []
    for r in rows:
        if not r.get("index"):
            continue
        name = str(r["index"]).strip()
        request_name = str(r.get("indexSymbol") or "").strip() or name
        targets.append((name, request_name))
    return targets, rows


def fetch_index(session: requests.Session, request_name: str, sleep: Sleep = time.sleep) -> List[dict]:
    return _get_json(session, INDEX_URL, {"index": request_name}, sleep)["data"]


def index_filename(name: str) -> str:
    return (name.replace(" ", "_").replace(":", "_").replace("/", "_").replace("&", "and")) + ".csv"


def stock_row(item: dict) -> list:
    return [item.get(k, "-") for k in SOURCE_KEYS]


def _atomic_write(path: Path, writer: Callable) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer(csv.writer(fh))
    tmp.replace(path)


def write_index_csv(path: Path, items: List[dict]) -> None:
    def _w(w):
        w.writerow(HEADER)
        for item in items:
            w.writerow(stock_row(item))
    _atomic_write(path, _w)


def write_master_csv(path: Path, rows: List[dict]) -> None:
    columns: List[str] = []
    for r in rows:
        for k in r:
            if k not in columns:
                columns.append(k)

    def _w(w):
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c, "") for c in columns])
    _atomic_write(path, _w)


def _has_data(path: Path) -> bool:
    """A finished file has at least one data row below the header."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with open(path, encoding="utf-8") as fh:
        return sum(1 for _ in fh) > 1


def run(session: requests.Session, out_dir: Path, force: bool = False, run_date: Optional[str] = None,
        sleep: Sleep = time.sleep) -> Dict[str, int]:
    """Download every index into out_dir/<run_date>/. Returns {"new", "skipped", "failed"}."""
    now = datetime.now()
    run_date = run_date or now.strftime("%Y%m%d")
    day_dir = out_dir / run_date
    stats = {"new": 0, "skipped": 0, "failed": 0, "empty": 0}

    targets, rows = list_indices(session, sleep)
    master = day_dir / f"NSE_ALL_INDICES_{now:%Y%m%d_%H%M%S}.csv"
    write_master_csv(master, rows)
    total = len(targets)
    log.info("Found %d indices; master list saved: %s", total, master)

    for n, (name, request_name) in enumerate(targets, 1):
        dest = day_dir / index_filename(name)
        if not force and _has_data(dest):
            stats["skipped"] += 1
            log.info("[%d/%d] %s already saved today, skipping", n, total, name)
            continue
        try:
            items = fetch_index(session, request_name, sleep)
            if items:
                write_index_csv(dest, items)
        except Exception as exc:  # keep going; a failed index is retried on the next run
            stats["failed"] += 1
            log.error("[%d/%d] Failed %s: %s", n, total, name, exc)
            continue
        if items:
            stats["new"] += 1
            log.info("[%d/%d] Saved %s (%d rows) | new=%d skipped=%d empty=%d failed=%d",
                     n, total, dest.name, len(items), stats["new"], stats["skipped"],
                     stats["empty"], stats["failed"])
        else:
            stats["empty"] += 1
            log.warning("[%d/%d] %s: NSE returned no constituents (no file written; retried next run)",
                        n, total, name)
        sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    return stats


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download all NSE index constituents to CSV files.")
    p.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT,
                   help="Root folder; files go to <out>/<YYYYMMDD>/ (default: data_nse_index)")
    p.add_argument("--force", action="store_true", help="Download indices already saved today again")
    p.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose, args.log_dir / f"nse_{datetime.now():%Y%m%d_%H%M%S}.log")
    try:
        stats = run(make_session(), args.out, force=args.force, sleep=time.sleep)
    except RuntimeError as exc:
        log.error("Could not get the NSE index list: %s", exc)
        return 2
    log.info("Done. new=%d skipped=%d empty=%d failed=%d -> %s",
             stats["new"], stats["skipped"], stats["empty"], stats["failed"], args.out)
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
