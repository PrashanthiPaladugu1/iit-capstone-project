"""Paths and limits for Agentic Research and Portfolio Maker (Nifty 50 only).

No path is written in code. Every path comes from config/paths.json (see the _help text in that file).
The only fixed locations are the bootstrap pair: this file and config/paths.json. Use the environment
variable ARPM_PATHS_FILE to point at a different paths file.

This module uses only the standard library and runs on Python 3.9+, so setup.sh and the bin/ scripts can call it
before the virtual environment exists:

    python3 project-code/config.py shell        # NAME='value' lines for a shell: eval "$(...)"
    python3 project-code/config.py get usage_db # one resolved path
    python3 project-code/config.py show         # all resolved paths
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

APP_NAME = "Agentic Research and Portfolio Maker"
CODE_DIR = Path(__file__).resolve().parent                      # bootstrap: where this file is

MAX_AGENT_STEPS = 6      # model <-> tool round trips per question (guardrail G8)
MAX_TOOL_CALLS = 12      # tool calls per question (guardrail G8)
CALL_TIMEOUT_S = 180.0   # one model call

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class PathsError(ValueError):
    pass


def paths_file() -> Path:
    override = os.environ.get("ARPM_PATHS_FILE")
    return Path(override).expanduser() if override else CODE_DIR.parent / "config" / "paths.json"


def _load() -> tuple[dict, dict, Path]:
    file = paths_file().resolve()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PathsError(f"paths file not found: {file}") from exc
    except ValueError as exc:
        raise PathsError(f"paths file is not valid JSON: {file} ({exc})") from exc
    paths, patterns = data.get("paths"), data.get("patterns", {})
    if not isinstance(paths, dict) or "root" not in paths:
        raise PathsError(f"{file}: needs a 'paths' object with a 'root' entry")
    return paths, patterns, file


def _expand(text: str) -> str:
    return os.path.expandvars(os.path.expanduser(text))


def _resolve(name: str, paths: dict, root: Path, stack: tuple = ()) -> Path:
    if name in stack:
        raise PathsError(f"circular reference: {' -> '.join(stack + (name,))}")
    if name not in paths:
        raise PathsError(f"unknown path entry: {name}")
    raw = _expand(str(paths[name]))

    def sub(match: re.Match) -> str:
        return str(_resolve(match.group(1), paths, root, stack + (name,)))

    text = _PLACEHOLDER.sub(sub, raw)
    path = Path(text)
    return path if path.is_absolute() else root / path


def _root(paths: dict, file: Path) -> Path:
    raw = Path(_expand(str(paths["root"])))
    return (raw if raw.is_absolute() else file.parent / raw).resolve()


def all_paths() -> dict[str, Path]:
    paths, _, file = _load()
    root = _root(paths, file)
    out = {"root": root}
    for name in paths:
        if name != "root":
            out[name] = _resolve(name, paths, root)
    return out


def get(name: str) -> Path:
    """One resolved path from the 'paths' section, for example get('usage_db')."""
    paths, _, file = _load()
    root = _root(paths, file)
    return root if name == "root" else _resolve(name, paths, root)


def pattern(name: str, **values: str) -> Path:
    """A path built from the 'patterns' section, for example pattern('price_file', symbol='TCS')."""
    paths, patterns, file = _load()
    if name not in patterns:
        raise PathsError(f"unknown pattern: {name}")
    root = _root(paths, file)
    resolved = {k: str(_resolve(k, paths, root)) if k != "root" else str(root) for k in paths}
    for key, value in values.items():
        if not re.fullmatch(r"[A-Za-z0-9._&-]+", str(value)):          # keep a symbol from escaping its folder
            raise PathsError(f"bad value for {key}: {value!r}")
    resolved.update(values)

    def sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in resolved:
            raise PathsError(f"pattern '{name}' needs a value for {{{key}}}")
        return resolved[key]

    text = _PLACEHOLDER.sub(sub, _expand(str(patterns[name])))
    path = Path(text)
    return path if path.is_absolute() else root / path


# Named accessors used by the app. They read paths.json each time, so an edit applies without a restart.
def data_root() -> Path:
    return get("data_root")


def db_dir() -> Path:
    return get("db_dir")


def chroma_dir() -> Path:
    return get("chroma_dir")


def duckdb_file() -> Path:
    return get("duckdb_file")


def portfolios_db() -> Path:
    return get("portfolios_db")


def chats_db() -> Path:
    return get("chats_db")


def prices_dir() -> Path:
    return get("prices_dir")


def documents_dir() -> Path:
    return get("documents_dir")


def nifty50_list() -> Path:
    return get("nifty50_list")


def all_stocks_list() -> Path:
    return get("all_stocks_list")


def usage_db() -> Path:
    return get("usage_db")


def settings_db() -> Path:
    return get("settings_db")


def _shell_name(key: str) -> str:
    return "ARPM_ROOT" if key == "root" else key.upper()


def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "shell":
            for key, value in all_paths().items():
                print(f"{_shell_name(key)}={shlex.quote(str(value))}")
        elif cmd == "get" and len(argv) == 3:
            print(get(argv[2]))
        elif cmd == "show":
            for key, value in all_paths().items():
                print(f"{key:20} {value}")
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except PathsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
