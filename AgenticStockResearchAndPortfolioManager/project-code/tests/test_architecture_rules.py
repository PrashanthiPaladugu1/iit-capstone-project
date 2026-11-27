"""The gateway is the only door to a model. No other app file may import a model SDK or call a model service."""
import re
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
ALLOWED = {"providers.py"}                       # the only module allowed to talk to model services
FORBIDDEN = [r"^\s*(import|from)\s+ollama\b", r"^\s*(import|from)\s+openai\b", r"^\s*(import|from)\s+huggingface_hub\b",
             r"^\s*(import|from)\s+transformers\b", r"^\s*(import|from)\s+sentence_transformers\b",
             r"api/chat", r"api/embed", r"chat/completions", r"localhost:11434"]


def app_files():
    for f in CODE.glob("*.py"):
        yield f


def test_only_providers_py_talks_to_model_services():
    offenders = []
    for f in app_files():
        if f.name in ALLOWED or re.fullmatch(r"providers\.v\d+\.py", f.name):   # backups of providers.py (no-delete rule)
            continue
        text = f.read_text(encoding="utf-8")
        for pattern in FORBIDDEN:
            if re.search(pattern, text, re.M):
                offenders.append(f"{f.name}: {pattern}")
    assert offenders == []


def test_no_hard_coded_database_or_data_paths_in_code():
    bad = re.compile(r"(project-db|app_data|screener-document-download|/Users/|\.sqlite\b.*=\s*['\"]/)")
    offenders = []
    for f in app_files():
        if f.name == "config.py":
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{f.name}:{n}")
    assert offenders == []
