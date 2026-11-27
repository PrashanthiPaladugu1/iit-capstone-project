"""Constants and default paths. Paths are anchored to the project root, not the CWD."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_WATCHLIST = PROJECT_ROOT / "watchlist.txt"
DEFAULT_AUTH = PROJECT_ROOT / "screener_auth.json"
DEFAULT_HISTORY = PROJECT_ROOT / "downloaded_history.json"
DEFAULT_TRACKER = PROJECT_ROOT / "download_tracker.txt"  # one finished symbol per line
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"  # data/{SYMBOL}/...
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"     # logs/run_<timestamp>.log + .summary.json
CSV_GLOB = "equitydata-screener-all-stocks-*.csv"  # Screener screen export in the project root
REFERENCE_DIR = PROJECT_ROOT / "Reference-Files"   # index lists for --index (e.g. nifty-50.csv)

BASE_URL = "https://www.screener.in"
COMPANY_URL = BASE_URL + "/company/{symbol}/{view}"  # view = "consolidated/" or ""

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
DEFAULT_MIN_DELAY = 1.0
DEFAULT_MAX_DELAY = 2.0
DEFAULT_WORKERS = 1   # stocks processed in parallel; each stock runs end to end on one worker
MAX_WORKERS = 8

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
ALLOWED_EXTENSIONS = {".pdf", ".zip", ".ppt", ".pptx"}

# CLI --types value -> Doc.kind
KIND_MAP = {"annual": "Annual_Report", "transcript": "Transcript", "ppt": "PPT"}

LOGGER_NAME = "screener_downloader"
