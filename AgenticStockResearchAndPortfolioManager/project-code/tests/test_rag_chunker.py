import pytest

import rag_chunker as rc


def test_short_text_is_one_chunk():
    assert rc.chunk_text("hello world", 1000, 150) == ["hello world"]


def test_empty_text_gives_no_chunks():
    assert rc.chunk_text("   \n  ", 1000, 150) == []


def test_chunks_respect_size_and_overlap():
    text = " ".join(f"word{i}" for i in range(600))          # about 4,000 characters
    chunks = rc.chunk_text(text, 1000, 150)
    assert len(chunks) >= 4
    assert all(len(c) <= 1000 for c in chunks)
    # consecutive chunks share text (overlap)
    for a, b in zip(chunks, chunks[1:]):
        assert a[-40:].split()[-1] in b


def test_every_word_is_kept():
    words = [f"w{i}" for i in range(2000)]
    chunks = rc.chunk_text(" ".join(words), 500, 80)
    seen = set(" ".join(chunks).split())
    assert seen == set(words)


def test_no_endless_loop_on_text_without_spaces():
    chunks = rc.chunk_text("x" * 5000, 1000, 150)
    assert 5 <= len(chunks) <= 7


def test_bad_settings_rejected():
    with pytest.raises(ValueError):
        rc.chunk_text("abc", 100, 100)
    with pytest.raises(ValueError):
        rc.chunk_text("abc", 0, 0)


def test_parse_document_name():
    assert rc.parse_document_name("Transcript_Oct_2024.pdf") == ("transcript", 2024, "Oct")
    assert rc.parse_document_name("Annual_Report_2023.pdf") == ("annual_report", 2023, "")
    assert rc.parse_document_name("PPT_Jan_2016_2.pdf") == ("presentation", 2016, "Jan")
    assert rc.parse_document_name("Financials_TCS.xlsx") is None
    assert rc.parse_document_name("Annual_Report_2013.zip") is None


def test_chunk_pages_keeps_page_numbers_and_counts_empty_pages():
    pages = ["First page text " * 10, "   ", "Third page " * 200]
    chunks, stats = rc.chunk_pages(pages, 500, 50, split="page")
    assert {c.page for c in chunks} == {1, 3}
    assert stats == {"pages": 3, "empty_pages": 1, "chunks": len(chunks)}
    assert [c.n for c in chunks if c.page == 3] == list(range(len([c for c in chunks if c.page == 3])))


def test_section_split_not_built_yet():
    with pytest.raises(ValueError, match="section"):
        rc.chunk_pages(["abc"], 500, 50, split="section")


def test_tier_selection(tmp_path):
    for name in ["Transcript_Jan_2024.pdf", "Transcript_Oct_2023.pdf", "Annual_Report_2021.pdf", "Annual_Report_2022.pdf",
                 "Annual_Report_2023.pdf", "Annual_Report_2024.pdf", "PPT_Jan_2024.pdf", "PPT_Oct_2023.pdf",
                 "PPT_Jul_2023.pdf", "PPT_Apr_2023.pdf", "PPT_Jan_2023.pdf", "PPT_Oct_2022.pdf", "Financials_X.xlsx", "a.zip"]:
        (tmp_path / name).write_bytes(b"")
    t1 = [f.name for f in rc.select_documents(tmp_path, tiers=(1,))]
    assert sorted(t1) == ["Transcript_Jan_2024.pdf", "Transcript_Oct_2023.pdf"]
    t2 = [f.name for f in rc.select_documents(tmp_path, tiers=(2,))]
    assert sorted(t2) == ["Annual_Report_2022.pdf", "Annual_Report_2023.pdf", "Annual_Report_2024.pdf"]
    t3 = [f.name for f in rc.select_documents(tmp_path, tiers=(3,))]
    assert len(t3) == 5 and "PPT_Oct_2022.pdf" not in t3 and "PPT_Jan_2024.pdf" in t3
    assert len(rc.select_documents(tmp_path, tiers=(1, 2, 3))) == 10


def test_select_documents_counts_are_options(tmp_path):
    for y in range(2018, 2025):
        (tmp_path / f"Annual_Report_{y}.pdf").write_bytes(b"")
    assert len(rc.select_documents(tmp_path, tiers=(2,), annual_reports=5)) == 5
    assert [f.name for f in rc.select_documents(tmp_path, tiers=(2,), annual_reports=2)] == \
        ["Annual_Report_2023.pdf", "Annual_Report_2024.pdf"]
