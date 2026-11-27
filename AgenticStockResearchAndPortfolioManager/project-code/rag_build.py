"""Build or rebuild the document index (RAG). Run it through bin/rag_build.sh so it uses the app environment.

Examples:
    bin/rag_build.sh --estimate-only                 # count pages and chunks, time one embedding batch, change nothing
    bin/rag_build.sh --trial --symbols TCS --yes     # one stock, to check speed and quality (collection stays unfinished)
    bin/rag_build.sh --annual-reports 5 --yes        # latest 5 annual reports per stock
    bin/rag_build.sh --size 1500 --overlap 200 --yes # a new collection for another chunk size; the old one is kept

Rules: nothing is deleted. Each (embedding model, size, overlap, split) has its own collection. A finished file is
skipped on the next run, so a stopped run continues where it stopped. The collection is marked complete (and so becomes
searchable) only when ALL Nifty 50 stocks were processed with no failed file.
"""
from __future__ import annotations

import argparse
import csv
import os
import signal
import sys
import time
from pathlib import Path

import config
import rag_chunker
from model_settings import SettingsStore


def parse_args(argv, settings: SettingsStore | None = None):
    settings = settings or SettingsStore()
    saved = settings.get_value("chunking")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--size", type=int, default=saved["size"], help=f"chunk size in characters (saved: {saved['size']})")
    p.add_argument("--overlap", type=int, default=saved["overlap"], help=f"overlap in characters (saved: {saved['overlap']})")
    p.add_argument("--split", default=saved["split"], choices=["page"], help="only 'page' is built")
    p.add_argument("--tiers", default="1,2,3", help="1 transcripts, 2 latest annual reports, 3 latest presentations")
    p.add_argument("--annual-reports", type=int, default=3, help="how many latest annual reports per stock in tier 2 (default 3)")
    p.add_argument("--symbols", default=None, help="comma list, for example TCS,INFY (default: all Nifty 50)")
    p.add_argument("--trial", action="store_true", help="one stock only (first of --symbols, else TCS); not marked complete")
    p.add_argument("--exact-estimate", action="store_true", help="read every PDF for an exact count (slow: about 8 s per stock)")
    p.add_argument("--estimate-only", action="store_true", help="count and time, then stop")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation (needed for background runs)")
    a = p.parse_args(argv)
    a.tiers = [int(t) for t in str(a.tiers).split(",") if t.strip()]
    if not a.tiers or any(t not in (1, 2, 3) for t in a.tiers):
        p.error("--tiers must be numbers from 1 to 3, for example 1,2,3")
    if a.size < 200 or a.size > 8000 or a.overlap < 0 or a.overlap >= a.size // 2:
        p.error("size must be 200 to 8000 and overlap from 0 to less than half the size")
    if not 1 <= a.annual_reports <= 15:
        p.error("--annual-reports must be from 1 to 15")
    a.symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] if a.symbols else None
    return a


def nifty_symbols() -> list[str]:
    with open(config.nifty50_list(), newline="", encoding="utf-8-sig") as f:
        return [row["NSE Code"].strip() for row in csv.DictReader(f) if row.get("NSE Code", "").strip()]


def stock_folders(symbols: list[str]) -> dict[str, Path]:
    return {s: config.pattern("symbol_documents_dir", symbol=s) for s in symbols}


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds}s"


def progress_line(stock_no: int, stocks: int, done: int, total: int, elapsed: float) -> str:
    pct = 100 * done / total if total else 100
    rate = done / elapsed if elapsed > 0 and done else 0
    eta = f"ETA {format_duration((total - done) / rate)}" if rate else "ETA unknown"
    return (f"PROGRESS stock {stock_no}/{stocks} | chunks {done:,}/{total:,} ({pct:.0f}%) | "
            f"{rate:.1f} chunks/s | elapsed {format_duration(elapsed)} | {eta}")


CHUNKS_PER_PAGE = 3.6      # measured on TCS at 1000/150: 5,067 chunks from 1,413 pages. Scales roughly with 1000/size.


def estimate(folders: dict[str, Path], tiers, size: int, overlap: int, annual_reports: int = 3, quick: bool = False) -> dict:
    """Count files, pages and chunks without embedding. quick=True counts pages only (fast) and guesses the chunks;
    otherwise every PDF is read and chunked (exact, but about 8 s per stock)."""
    files = pages = chunks = empty = 0
    if quick:
        for symbol, folder in folders.items():
            if not folder.is_dir():
                continue
            for pdf in rag_chunker.select_documents(folder, tiers, annual_reports=annual_reports):
                try:
                    pages += rag_chunker.count_pages(pdf)
                    files += 1
                except Exception:
                    continue
        return {"files": files, "pages": pages, "empty_pages": 0, "chunks": int(pages * CHUNKS_PER_PAGE * 1000 / size),
                "quick": True}
    for symbol, folder in folders.items():
        if not folder.is_dir():
            continue
        for pdf in rag_chunker.select_documents(folder, tiers, annual_reports=annual_reports):
            try:
                _, stats = rag_chunker.chunk_pages(rag_chunker.read_pdf_pages(pdf), size, overlap)
            except Exception:
                continue
            files += 1
            pages += stats["pages"]
            empty += stats["empty_pages"]
            chunks += stats["chunks"]
    return {"files": files, "pages": pages, "empty_pages": empty, "chunks": chunks}


def log(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def main(argv=None) -> int:
    settings = SettingsStore()
    args = parse_args(sys.argv[1:] if argv is None else argv, settings)
    chunking = {"size": args.size, "overlap": args.overlap, "split": args.split}
    collection = settings.embedding_collection(chunking)
    every = nifty_symbols()
    symbols = args.symbols or every
    if args.trial:
        symbols = symbols[:1] if args.symbols else ["TCS"]
    unknown = [s for s in symbols if s not in every]
    if unknown:
        log(f"Not in the Nifty 50 list: {unknown}. Stopping.")
        return 2
    folders = stock_folders(symbols)

    from rag_store import RagStore
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))   # bin/rag_build_stop.sh
    store = RagStore(collection=collection)
    log(f"collection: {collection}  stocks: {len(symbols)}  tiers: {args.tiers}  size/overlap: {args.size}/{args.overlap}")
    log(f"already done in this collection: {store.status()['files_done']} files (they will be skipped)")

    log("counting pages (no embedding)...")
    est = estimate(folders, args.tiers, args.size, args.overlap, args.annual_reports, quick=not args.exact_estimate)
    sample = [f"sample text {i} " * 60 for i in range(32)]
    t0 = time.time()
    store.gateway.embed(sample, role="embedding", agent="rag_estimate")
    per_chunk = (time.time() - t0) / len(sample)
    minutes = est["chunks"] * per_chunk / 60
    kind = "about" if est.get("quick") else "exactly"
    log(f"files {est['files']}, pages {est['pages']}, chunks {kind} {est['chunks']:,}")
    log(f"embedding speed {1 / per_chunk:.1f} chunks per second -> about {minutes:.0f} minutes (rough; skipped files cost nothing)")
    if args.estimate_only:
        return 0
    if not args.yes:
        if input("Start? [y/N] ").strip().lower() != "y":
            log("Cancelled. Nothing changed.")
            return 1

    started = time.time()
    totals = {"files_done": 0, "files_skipped": 0, "files_failed": 0, "chunks": 0}
    run_id = store.start_run(" ".join(sys.argv[1:]))
    log(f"RUN {run_id} started (pid {os.getpid()}). Stop it safely with bin/rag_build_stop.sh; run the same command again to continue.")
    state = {"chunks": 0}
    symbol_no = 0

    def on_file(file, pages, chunks):
        state["chunks"] += chunks
        log(progress_line(symbol_no, len(symbols), state["chunks"], est["chunks"], time.time() - started))

    try:
        for symbol_no, symbol in enumerate(symbols, 1):
            log(f"[{symbol_no}/{len(symbols)}] {symbol}")
            if not folders[symbol].is_dir():
                log(f"  no document folder for {symbol}")
                continue
            res = store.ingest_stock(symbol, folders[symbol], size=args.size, overlap=args.overlap, tiers=args.tiers,
                                     annual_reports=args.annual_reports, log=log, on_file=on_file)
            for k in totals:
                totals[k] += res[k]
            log(f"  {symbol} done: {res}")
    except KeyboardInterrupt:
        store.finish_run(run_id, "stopped", totals, "stopped by signal")
        log(f"RUN {run_id} STOPPED by signal after {format_duration(time.time() - started)}. Totals so far: {totals}. Run the same command to continue.")
        return 130
    except Exception as exc:
        store.finish_run(run_id, "error", totals, f"{type(exc).__name__}: {exc}")
        log(f"RUN {run_id} ERROR: {type(exc).__name__}: {exc}. Totals so far: {totals}. Fix the cause and run the same command to continue.")
        return 1
    log(f"finished in {format_duration(time.time() - started)}: {totals}")

    full = not args.trial and set(symbols) == set(every)
    if full and store.status()["files_failed"] == 0:
        store.mark_complete()
        store.finish_run(run_id, "complete", totals, "collection marked complete")
        log("collection marked complete; it can be searched now")
    else:
        store.finish_run(run_id, "partial", totals, "not marked complete")
        log("collection NOT marked complete (trial, partial stock list, or failed files). Re-run the same command to continue.")
    log(f"final status: {store.status()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
