"""Download NSE daily bhavcopy files (sec_bhavdata_full_DDMMYYYY.csv) into data_stock_bhavcopy/.

    python3 code/nse_bhavcopy.py                    # last 1700 days, weekdays only; existing files skipped
    python3 code/nse_bhavcopy.py --days 30          # last 30 days
    python3 code/nse_bhavcopy.py --force            # download everything again

Ported from the nse_bhavcopy_downloader.ipynb Colab notebook, with two fixes:
  * It used `curl -s` without checking the HTTP status, so on market holidays NSE's 404 HTML page was
    saved as a ".csv". Here a 404 is counted as "missing" (holiday / not published) and nothing is saved,
    and every saved file must look like a bhavcopy CSV.
  * Files already on disk that are not a real bhavcopy (e.g. those HTML pages) are downloaded again.
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from config import DEFAULT_LOG_DIR, LOGGER_NAME, PROJECT_ROOT, USER_AGENT
from log_setup import setup_logging

log = logging.getLogger(LOGGER_NAME)

BASE_URL = "https://nsearchives.nseindia.com/products/content/"
DEFAULT_OUT = PROJECT_ROOT / "data_stock_bhavcopy"
DEFAULT_DAYS = 1700

MAX_RETRIES = 3
TIMEOUT = 30
MIN_DELAY, MAX_DELAY = 1.0, 1.5  # polite pause between requests
PROGRESS_EVERY = 50

Sleep = Callable[[float], None]


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    })
    return s


def trading_days(end: date, days: int) -> List[date]:
    """Weekdays among the `days` calendar days ending at `end`, newest first (NSE is closed Sat/Sun)."""
    out = []
    for n in range(days):
        d = end - timedelta(days=n)
        if d.weekday() < 5:
            out.append(d)
    return out


def filename(d: date) -> str:
    return f"sec_bhavdata_full_{d:%d%m%Y}.csv"


def url_for(d: date) -> str:
    return BASE_URL + filename(d)


def is_bhavcopy(content: bytes) -> bool:
    """A real bhavcopy starts with its CSV header ('SYMBOL, SERIES, ...'); an error page does not."""
    return content.lstrip()[:6].upper() == b"SYMBOL"


def _already_saved(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with open(path, "rb") as fh:
        return is_bhavcopy(fh.read(64))


def _fetch(session: requests.Session, d: date, sleep: Sleep) -> Optional[bytes]:
    """The file's bytes, or None if NSE has no file for that date (404). Raises RuntimeError after retries."""
    last = "unknown error"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url_for(d), timeout=TIMEOUT)
            if resp.status_code == 404:
                return None
            if resp.status_code == 200 and is_bhavcopy(resp.content):
                return resp.content
            last = (f"HTTP {resp.status_code}" if resp.status_code != 200
                    else "response is not a bhavcopy CSV (error page?)")
        except requests.RequestException as exc:
            last = str(exc)
        log.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, filename(d), last)
        if attempt < MAX_RETRIES:
            sleep(2 ** attempt)
    raise RuntimeError(f"Giving up on {filename(d)}: {last}")


def run(session: requests.Session, out_dir: Path, days: int, end: date, force: bool = False,
        sleep: Sleep = time.sleep) -> Dict[str, int]:
    """Download every weekday file. Returns {"new", "skipped", "missing", "failed"}."""
    stats = {"new": 0, "skipped": 0, "missing": 0, "failed": 0}
    dates = trading_days(end, days)
    total = len(dates)
    log.info("%d weekday(s) from %s back to %s -> %s", total, dates[0] if dates else end,
             dates[-1] if dates else end, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for n, d in enumerate(dates, 1):
        dest = out_dir / filename(d)
        if not force and _already_saved(dest):
            stats["skipped"] += 1
        else:
            try:
                content = _fetch(session, d, sleep)
            except Exception as exc:  # keep going; retried on the next run
                stats["failed"] += 1
                log.error("[%d/%d] Failed %s: %s", n, total, filename(d), exc)
                sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                continue
            if content is None:
                stats["missing"] += 1
                log.info("[%d/%d] %s not published (holiday?)", n, total, filename(d))
            else:
                tmp = dest.with_name(dest.name + ".part")
                tmp.write_bytes(content)
                tmp.replace(dest)
                stats["new"] += 1
                log.info("[%d/%d] Saved %s (%.0f KB)", n, total, dest.name, len(content) / 1024)
            sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        if n % PROGRESS_EVERY == 0 or n == total:
            log.info("Progress %d/%d (%.1f%%) | new=%d skipped=%d missing=%d failed=%d",
                     n, total, 100.0 * n / total, stats["new"], stats["skipped"],
                     stats["missing"], stats["failed"])
    return stats


def _iso_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date in YYYY-MM-DD format")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download NSE daily bhavcopy CSV files.")
    p.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT,
                   help="Folder for the files (default: data_stock_bhavcopy)")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS,
                   help="Calendar days to go back from the end date (weekends are skipped)")
    p.add_argument("--end-date", type=_iso_date, default=None, help="Newest date, YYYY-MM-DD (default: today)")
    p.add_argument("--force", action="store_true", help="Download files already saved again")
    p.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if args.days < 1:
        p.error("--days must be >= 1")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose, args.log_dir / f"bhavcopy_{datetime.now():%Y%m%d_%H%M%S}.log")
    end = args.end_date or date.today()
    stats = run(make_session(), args.out, args.days, end, force=args.force, sleep=time.sleep)
    log.info("Done. new=%d skipped=%d missing=%d failed=%d -> %s",
             stats["new"], stats["skipped"], stats["missing"], stats["failed"], args.out)
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
