"""Paths come from config/paths.json, not from code."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def write(tmp_path, data):
    f = tmp_path / "paths.json"
    f.write_text(json.dumps(data))
    return f


def test_real_file_resolves_and_databases_live_in_project_db():
    assert config.chroma_dir().name == "chroma" and config.chroma_dir().parent.name == "project-db"
    assert config.duckdb_file().parent.name == "project-db"
    assert config.usage_db().parent.name == "project-db"
    assert config.settings_db().parent.name == "project-db"
    assert config.portfolios_db().parent.name == "project-db"
    assert "project-code" not in str(config.usage_db())


def test_price_folder_has_50_files():
    assert len(list(config.prices_dir().glob("*.csv"))) == 50


def test_paths_file_override_changes_every_path(tmp_path, monkeypatch):
    f = write(tmp_path, {"paths": {"root": ".", "db_dir": "mydb", "usage_db": "{db_dir}/u.sqlite"}})
    monkeypatch.setenv("ARPM_PATHS_FILE", str(f))
    assert config.get("usage_db") == tmp_path.resolve() / "mydb" / "u.sqlite"


def test_absolute_value_is_kept(tmp_path, monkeypatch):
    f = write(tmp_path, {"paths": {"root": ".", "db_dir": "/mnt/ebs/db"}})
    monkeypatch.setenv("ARPM_PATHS_FILE", str(f))
    assert config.get("db_dir") == Path("/mnt/ebs/db")


def test_circular_reference_is_reported(tmp_path, monkeypatch):
    f = write(tmp_path, {"paths": {"root": ".", "a": "{b}/x", "b": "{a}/y"}})
    monkeypatch.setenv("ARPM_PATHS_FILE", str(f))
    with pytest.raises(config.PathsError, match="circular"):
        config.get("a")


def test_unknown_entry_and_missing_file(tmp_path, monkeypatch):
    f = write(tmp_path, {"paths": {"root": "."}})
    monkeypatch.setenv("ARPM_PATHS_FILE", str(f))
    with pytest.raises(config.PathsError, match="unknown path entry"):
        config.get("nope")
    monkeypatch.setenv("ARPM_PATHS_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(config.PathsError, match="not found"):
        config.get("root")


def test_pattern_and_symbol_cannot_escape_folder():
    assert config.pattern("price_file", symbol="TCS").name == "TCS.csv"
    assert config.pattern("financials_file", symbol="M&M").parent.name == "M&M"
    for bad in ("../x", "a/b", ""):
        with pytest.raises(config.PathsError):
            config.pattern("price_file", symbol=bad)


def test_shell_output_has_quoted_assignments(capsys):
    assert config._main(["config.py", "shell"]) == 0
    out = capsys.readouterr().out
    assert "DB_DIR=" in out and "ARPM_ROOT=" in out and "RUN_DIR=" in out
