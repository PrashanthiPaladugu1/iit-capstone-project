"""Command-line interface and run orchestration."""
from __future__ import annotations

import argparse
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

from auth import build_session
from config import (DEFAULT_AUTH, DEFAULT_HISTORY, DEFAULT_LOG_DIR, DEFAULT_MAX_DELAY,
                    DEFAULT_MIN_DELAY, DEFAULT_OUTPUT_DIR, DEFAULT_TRACKER, DEFAULT_WATCHLIST,
                    DEFAULT_WORKERS, KIND_MAP, LOGGER_NAME, MAX_WORKERS, PROJECT_ROOT,
                    REFERENCE_DIR)
from history import load_history
from http_client import Fetcher
from log_setup import default_log_path, setup_logging
from models import AuthError
from pipeline import process_symbol
from progress import Progress, fmt_duration
from symbols_csv import find_index_csv, find_latest_csv, read_symbols_from_csv
from tracker import load_tracker, mark_done
from watchlist import read_watchlist

log = logging.getLogger(LOGGER_NAME)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Incrementally download Screener.in documents.")
    p.add_argument("-w", "--watchlist", type=Path, default=DEFAULT_WATCHLIST)
    p.add_argument("-a", "--auth", type=Path, default=DEFAULT_AUTH)
    p.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    p.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER,
                   help="File listing finished symbols (one per line); these are skipped on later runs")
    p.add_argument("--force", action="store_true",
                   help="Ignore the tracker file and process every symbol again "
                        "(already downloaded files are still skipped by the history)")
    p.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                   help="Root folder; files go to <output-dir>/<SYMBOL>/")
    p.add_argument("-s", "--symbols", "--stock", dest="symbols", nargs="+", action="extend",
                   metavar="SYMBOL",
                   help="Symbols to process instead of the watchlist/CSV; --stock may be repeated "
                        "(e.g. --stock INFY, or --stock INFY --stock TCS)")
    p.add_argument("--csv", type=Path, help="Screener screen-export CSV to take symbols from "
                   "(NSE Code, else BSE Code); used instead of the watchlist")
    p.add_argument("--all", action="store_true",
                   help="Process every stock in the newest equitydata-screener-all-stocks-*.csv "
                        "in the project root")
    p.add_argument("--index", metavar="NAME",
                   help="Process the stocks of an index list in Reference-Files/, matched by file "
                        "name ignoring case and '-'/'_' (e.g. --index Nifty50 -> nifty-50.csv)")
    p.add_argument("--start", type=int, default=0,
                   help="With --csv/--all/--index: skip the first N symbols")
    p.add_argument("--limit", type=int,
                   help="With --csv/--all/--index: process at most N symbols")
    p.add_argument("--types", nargs="+", choices=list(KIND_MAP), default=list(KIND_MAP),
                   help="Document types to fetch")
    p.add_argument("--no-excel", action="store_true", help="Skip the 'Export to Excel' download")
    p.add_argument("--standalone", action="store_true",
                   help="Use the standalone page instead of /consolidated/")
    p.add_argument("--min-delay", type=float, default=DEFAULT_MIN_DELAY,
                   help="Min seconds between requests")
    p.add_argument("--max-delay", type=float, default=DEFAULT_MAX_DELAY,
                   help="Max seconds between requests")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"Stocks to process in parallel (1-{MAX_WORKERS}). Each stock still runs "
                        "end to end on a single worker; every worker keeps its own delays, so the "
                        "request rate grows with this number")
    p.add_argument("--dry-run", action="store_true", help="List new documents without downloading")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    p.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR,
                   help="Folder for run logs: <log-dir>/run_<timestamp>.log (+ .summary.json)")
    p.add_argument("--log-file", type=Path, help="Write the log to this file instead of the default")
    args = p.parse_args(argv)
    if args.index and (args.all or args.csv):
        p.error("--index cannot be combined with --all or --csv")
    if args.min_delay < 0 or args.max_delay < args.min_delay:
        p.error("delays must satisfy 0 <= --min-delay <= --max-delay")
    if not 1 <= args.workers <= MAX_WORKERS:
        p.error(f"--workers must be between 1 and {MAX_WORKERS}")
    if args.start < 0:
        p.error("--start must be >= 0")
    if args.limit is not None and args.limit < 1:
        p.error("--limit must be >= 1")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    log_path = args.log_file or default_log_path(args.log_dir)
    summary_path = log_path.with_suffix(".summary.json")
    setup_logging(args.verbose, log_path)
    log.info("Log file: %s", log_path)

    csv_path: Optional[Path] = None
    try:
        if args.symbols:
            symbols = args.symbols
        else:
            csv_path = args.csv
            if args.index:
                csv_path = find_index_csv(REFERENCE_DIR, args.index)
            elif args.all and csv_path is None:
                csv_path = find_latest_csv(PROJECT_ROOT)
                if csv_path is None:
                    raise FileNotFoundError(f"--all: no {PROJECT_ROOT}/equitydata-screener-all-stocks-*.csv found")
            if csv_path:
                log.info("Reading symbols from %s", csv_path)
                symbols = read_symbols_from_csv(csv_path, args.start, args.limit)
            else:
                symbols = read_watchlist(args.watchlist)
        session = build_session(args.auth)
    except (FileNotFoundError, ValueError, AuthError) as exc:
        log.error("%s", exc)
        return 2
    if not symbols:
        log.error("No symbols to process")
        return 2

    all_symbols = symbols
    tracked = set() if args.force else load_tracker(args.tracker)
    # positions[i] = index in the full list of the i-th symbol of this run (for the resume hint)
    positions = [i for i, s in enumerate(all_symbols) if s.upper() not in tracked]
    symbols = [all_symbols[i] for i in positions]
    if len(symbols) < len(all_symbols):
        log.info("Skipping %d symbol(s) already done in %s (use --force to process them again)",
                 len(all_symbols) - len(symbols), args.tracker)
    if not symbols:
        log.info("Nothing to do: all %d symbol(s) are already done (use --force to process them again)",
                 len(all_symbols))
        return 0

    kinds = {KIND_MAP[t] for t in args.types}
    history = load_history(args.history)
    progress = Progress(len(symbols))
    stop = threading.Event()  # set on Ctrl+C / expired session so workers stop taking new work

    def run_one(index: int, symbol: str, fetcher: Fetcher) -> None:
        """One stock, start to finish, on the calling thread."""
        log.info(progress.begin(symbol))
        try:
            stats = process_symbol(symbol, fetcher, history, args.output_dir,
                                   args.history, kinds, args.dry_run,
                                   excel=not args.no_excel, standalone=args.standalone, stop=stop)
        except AuthError:
            raise
        except Exception:
            log.exception("[%s] Unexpected error; continuing with next symbol", symbol)
            log.info(progress.record_error(symbol, index))
            return
        log.info(progress.finish(symbol, stats, index))
        # Only a complete, clean, real run counts as done; failures and interrupted stocks are retried.
        if not args.dry_run and not stats.get("failed") and not stop.is_set():
            mark_done(args.tracker, symbol)

    def run_sequential() -> None:
        fetcher = Fetcher(session, args.min_delay, args.max_delay)
        for index, symbol in enumerate(symbols):
            run_one(index, symbol, fetcher)

    def run_parallel() -> None:
        """Whole stocks are the unit of work: a worker takes one symbol and finishes it before
        taking the next. Each worker thread has its own session/fetcher (requests.Session is
        not meant to be shared across threads)."""
        local = threading.local()
        auth_errors: List[AuthError] = []

        def task(index: int, symbol: str) -> None:
            if stop.is_set():
                return
            try:
                if getattr(local, "fetcher", None) is None:
                    local.fetcher = Fetcher(build_session(args.auth), args.min_delay, args.max_delay)
                run_one(index, symbol, local.fetcher)
            except AuthError as exc:
                auth_errors.append(exc)
                stop.set()

        pool = ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="stock")
        futures = [pool.submit(task, i, s) for i, s in enumerate(symbols)]
        try:
            for fut in as_completed(futures):
                fut.result()
        finally:
            stop.set()
            if not all(f.done() for f in futures):
                log.warning("Stopping: waiting for in-flight stocks to finish their current file")
            pool.shutdown(wait=True, cancel_futures=True)
        if auth_errors:
            raise auth_errors[0]

    preview = ", ".join(symbols[:10]) + (" ..." if len(symbols) > 10 else "")
    log.info("Processing %d symbol(s) with %d worker(s): %s", len(symbols), args.workers, preview)
    exit_code = 0
    interrupted = False
    try:
        if args.workers > 1:
            run_parallel()
        else:
            run_sequential()
    except AuthError as exc:
        log.error("%s. Re-export screener_auth.json and retry.", exc)
        exit_code = 3
    except KeyboardInterrupt:
        interrupted = True
        exit_code = 130
        log.warning("Interrupted after %d/%d symbols; history saved up to the last completed download",
                    progress.done, progress.total)
        if csv_path is not None:
            offset = progress.resume_offset()
            resume_pos = positions[offset] if offset < len(positions) else len(all_symbols)
            log.warning("Resume with: python3 code/download_screener_docs.py --csv %s --start %d",
                        csv_path, args.start + resume_pos)
    else:
        t = progress.totals
        log.info("Done. symbols=%d new=%d skipped=%d failed=%d elapsed %s",
                 progress.done, t["new"], t["skipped"], t["failed"], fmt_duration(progress.elapsed()))
        if progress.failed_symbols:
            log.info("Symbols with failures (%d): %s", len(progress.failed_symbols),
                     ", ".join(progress.failed_symbols))
        exit_code = 1 if t["failed"] else 0
    finally:
        progress.write_summary(summary_path, interrupted=interrupted)
        log.info("Summary written to %s", summary_path)
    return exit_code
