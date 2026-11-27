"""Paths, defaults and limits for Agentic Research and Portfolio Maker (Nifty 50 only)."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Agentic Research and Portfolio Maker"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

PRICES_DIR = PROJECT_ROOT / "data_stock_bhavcopy_nifty50"        # one <SYMBOL>.csv per stock
NIFTY50_LIST = PROJECT_ROOT / "Reference-Files" / "nifty-50.csv"  # Name, NSE Code, Industry Group, ...
APP_DATA_DIR = Path(os.environ.get("ARPM_DATA_DIR", PROJECT_ROOT / "app_data"))  # usage log, portfolios
USAGE_DB = APP_DATA_DIR / "usage.sqlite"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("ARPM_MODEL", "mistral:7b")
ALLOWED_MODELS = ("mistral:7b", "gemma4:12b", "gemma4:e4b", "phi4-mini", "llama3.2:1b", "nomic-embed-text")

MAX_AGENT_STEPS = 6          # model <-> tool round trips per question
MAX_TOOL_CALLS = 12          # tool calls per question
CALL_TIMEOUT_S = 180
