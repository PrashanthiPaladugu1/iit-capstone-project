import pymupdf
import pytest

import rag_build as rb
from model_settings import SettingsStore


def make_pdf(path, text):
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 550, 800), text, fontsize=10)
    doc.save(str(path))
    doc.close()


def test_collection_name_follows_command_line_values(tmp_path):
    s = SettingsStore(tmp_path / "s.sqlite")
    saved = s.embedding_collection()
    other = s.embedding_collection({"size": 1500, "overlap": 200, "split": "page"})
    assert saved.endswith("-page-c1000-o150") and other.endswith("-page-c1500-o200")


def test_parse_args_defaults_come_from_saved_settings(tmp_path):
    s = SettingsStore(tmp_path / "s.sqlite")
    a = rb.parse_args([], settings=s)
    assert (a.size, a.overlap, a.split) == (1000, 150, "page") and a.tiers == [1, 2, 3] and a.symbols is None


def test_parse_args_overrides(tmp_path):
    s = SettingsStore(tmp_path / "s.sqlite")
    a = rb.parse_args(["--size", "1500", "--overlap", "200", "--tiers", "1", "--symbols", "tcs,infy", "--trial"], settings=s)
    assert (a.size, a.overlap, a.tiers, a.symbols, a.trial) == (1500, 200, [1], ["TCS", "INFY"], True)


def test_estimate_counts_pages_without_embedding(tmp_path):
    folder = tmp_path / "data" / "ACME"
    folder.mkdir(parents=True)
    make_pdf(folder / "Transcript_Oct_2024.pdf", "word " * 300)
    est = rb.estimate({"ACME": folder}, tiers=(1,), size=500, overlap=50)
    assert est["files"] == 1 and est["pages"] == 1 and est["chunks"] >= 3


def test_bad_overlap_is_refused(tmp_path):
    s = SettingsStore(tmp_path / "s.sqlite")
    with pytest.raises(SystemExit):
        rb.parse_args(["--size", "1000", "--overlap", "900"], settings=s)


def test_format_duration():
    assert rb.format_duration(45) == "45s"
    assert rb.format_duration(125) == "2m 05s"
    assert rb.format_duration(3725) == "1h 02m"


def test_progress_line_has_counts_rate_and_eta():
    line = rb.progress_line(stock_no=2, stocks=50, done=1000, total=10000, elapsed=100.0)
    assert "stock 2/50" in line and "1,000/10,000" in line and "10%" in line
    assert "10.0 chunks/s" in line and "ETA 15m 00s" in line


def test_progress_line_without_data_yet_has_no_eta():
    assert "ETA unknown" in rb.progress_line(1, 50, 0, 10000, 5.0)


def test_estimate_respects_annual_report_and_presentation_limits(tmp_path):
    folder = tmp_path / "data" / "ACME"
    folder.mkdir(parents=True)
    for y in (2021, 2022, 2023, 2024, 2025):
        make_pdf(folder / f"Annual_Report_{y}.pdf", "word " * 100)
    few = rb.estimate({"ACME": folder}, tiers=(2,), size=500, overlap=50, annual_reports=2)
    many = rb.estimate({"ACME": folder}, tiers=(2,), size=500, overlap=50, annual_reports=5)
    assert few["files"] == 2 and many["files"] == 5


def test_parse_args_annual_report_count(tmp_path):
    s = SettingsStore(tmp_path / "s.sqlite")
    assert rb.parse_args([], settings=s).annual_reports == 3
    assert rb.parse_args(["--annual-reports", "5"], settings=s).annual_reports == 5


def test_quick_estimate_counts_pages_only(tmp_path):
    folder = tmp_path / "data" / "ACME"
    folder.mkdir(parents=True)
    make_pdf(folder / "Transcript_Oct_2024.pdf", "word " * 300)
    est = rb.estimate({"ACME": folder}, tiers=(1,), size=1000, overlap=100, quick=True)
    assert est["files"] == 1 and est["pages"] == 1 and est["quick"] is True and est["chunks"] == int(rb.CHUNKS_PER_PAGE)
