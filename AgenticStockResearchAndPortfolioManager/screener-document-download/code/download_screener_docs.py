#!/usr/bin/env python3
"""Entry point: incrementally download Annual Reports, Transcripts, PPTs and the Excel export.

Usage (from the project root):
    python code/download_screener_docs.py                  # process watchlist.txt
    python code/download_screener_docs.py -s TCS INFY      # ad-hoc symbols
    python code/download_screener_docs.py --dry-run        # list what would be downloaded

Output goes to data/{SYMBOL}/; progress is tracked in downloaded_history.json.
Module layout is described in context/CONTEXT.md.
"""
import sys

from cli import main

if __name__ == "__main__":
    sys.exit(main())
