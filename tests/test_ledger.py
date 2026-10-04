import json

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


def test_a_range_already_covered_by_other_reads_is_not_a_first_read(tmp_path):
    path = _book(tmp_path)
    before = path.read_bytes()
    assert ledger.record(path, url=URL, byte_range=(120, 280), sha256="d" * 64, read_at="2026-09-09T00:00:00.000Z",
                         read_by="exploration") is False
    assert path.read_bytes() == before  # nothing new was read, so nothing is logged


def test_require_seen_checks_without_writing(tmp_path):
    path = _book(tmp_path)
    book = ledger.load(path)
    assert ledger.require_seen(book, url=URL, byte_range=(100, 199), sha256="a" * 64)["first_read_by"] == "V3D-EXP-0001"
    assert ledger.require_seen(book, url=URL, byte_range=(120, 280), sha256="e" * 64) is None  # covered, not exact
    with pytest.raises(ledger.HoldoutViolation, match="never read before"):
        ledger.require_seen(book, url=URL, byte_range=(250, 350), sha256="e" * 64)
    with pytest.raises(ledger.LedgerError, match="source changed"):
        ledger.require_seen(book, url=URL, byte_range=(100, 199), sha256="0" * 64)


def test_extends_accepts_growth_and_names_every_rewrite(tmp_path):
    earlier = ledger.load(_book(tmp_path))
    later = json.loads(json.dumps(earlier))
    later["entries"].append({"url": URL, "byte_range": [500, 599], "sha256": "c" * 64,
                             "first_read_at": "2026-05-01T00:00:00.000Z", "first_read_by": "V3D-EXP-0003"})
    assert ledger.extends(earlier, later) == []
    later["entries"][0]["first_read_at"] = "2026-04-01T00:00:00.000Z"   # a backdated or postdated read
    del later["entries"][1]                                           # a forgotten read
    problems = ledger.extends(earlier, later)
    assert any("first_read_at changed" in p for p in problems) and any("entry removed" in p for p in problems)


@pytest.mark.parametrize("entry, problem", [
    ({"url": URL, "byte_range": [9, 1], "sha256": "a" * 64, "first_read_at": "2026-01-01T00:00:00Z",
      "first_read_by": "x"}, "byte_range"),
    ({"url": URL, "byte_range": [1, 9], "sha256": "xyz", "first_read_at": "2026-01-01T00:00:00Z",
      "first_read_by": "x"}, "sha256"),
    ({"url": URL, "byte_range": [1, 9], "sha256": "a" * 64, "first_read_at": "2026-01-01 00:00:00",
      "first_read_by": "x"}, "first_read_at"),
    ({"url": URL, "byte_range": [1, 9], "sha256": "a" * 64}, "missing first_read_at"),
])
def test_a_malformed_ledger_is_refused(tmp_path, entry, problem):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"schema": ledger.SCHEMA, "entries": [entry]}), encoding="utf-8")
    with pytest.raises(ledger.LedgerError, match=problem):
        ledger.load(path)


def test_concurrent_writers_wait_for_the_lock(tmp_path):
    path = _book(tmp_path)
    lock = path.with_name(f".{path.name}.lock")
    lock.write_text("", encoding="utf-8")                     # another writer holds the ledger
    with pytest.raises(ledger.LedgerError, match="locked by another process"):
        with ledger._locked(path, timeout_s=0.1):
            pass
    lock.unlink()
    assert ledger.record(path, url=URL, byte_range=(700, 799), sha256="b" * 64,
                         read_at="2026-06-01T00:00:00.000Z", read_by="V3D-EXP-0004") is True
    assert not lock.exists()


def test_saving_is_byte_stable(tmp_path):
    path = _book(tmp_path)
    ledger.save(path, ledger.load(path))
    once = path.read_bytes()
    ledger.save(path, ledger.load(path))
    assert path.read_bytes() == once
