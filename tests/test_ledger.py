import pytest

from rain_pipeline import ledger

URL = "https://example.org/a.dat"


def _book(tmp_path):
    path = tmp_path / "ledger.json"
    ledger.record(path, url=URL, byte_range=(100, 199), sha256="a" * 64, read_at="2026-01-01T00:00:00.000Z",
                  read_by="V3D-EXP-0001")
    ledger.record(path, url=URL, byte_range=(150, 299), sha256="b" * 64, read_at="2026-03-01T00:00:00.000Z",
                  read_by="V3D-EXP-0002")
    return path


def test_first_read_is_logged_once_and_changed_content_is_refused(tmp_path):
    path = _book(tmp_path)
    again = ledger.record(path, url=URL, byte_range=(100, 199), sha256="a" * 64, read_at="2026-09-09T00:00:00.000Z",
                          read_by="someone else")
    assert again is False
    assert ledger.load(path)["entries"][0]["first_read_by"] == "V3D-EXP-0001"
    with pytest.raises(ValueError, match="source changed"):
        ledger.record(path, url=URL, byte_range=(100, 199), sha256="c" * 64, read_at="2026-09-09T00:00:00.000Z",
                      read_by="x")


def test_unseen_bytes_count_overlapping_reads_once(tmp_path):
    book = ledger.load(_book(tmp_path))
    assert ledger.bytes_unseen(book, [(URL, (100, 299))]) == 0          # the union covers 100..299
    assert ledger.bytes_unseen(book, [(URL, (0, 399))]) == 200          # 0..99 and 300..399
    assert ledger.bytes_unseen(book, [("https://example.org/b.dat", (0, 9))]) == 10
    assert ledger.bytes_unseen(ledger.load(tmp_path / "missing.json"), [(URL, (0, 9))]) == 10


def test_bytes_read_before_a_registration(tmp_path):
    book = ledger.load(_book(tmp_path))
    wanted = [(URL, (0, 399))]
    assert ledger.bytes_read_before(book, wanted, "2025-12-31T00:00:00.000Z") == 0
    assert ledger.bytes_read_before(book, wanted, "2026-02-01T00:00:00.000Z") == 100   # only the January read
    assert ledger.bytes_read_before(book, wanted, "2026-04-01T00:00:00.000Z") == 200   # both, overlap counted once
    assert ledger.bytes_read_before(book, wanted, "2026-03-01T00:00:00.000Z") == 100   # a read at the same instant is not "before"
