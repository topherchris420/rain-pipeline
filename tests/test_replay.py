"""A replay re-executes a recorded run from its registration alone and says exactly what it found."""

import json

import pytest
from conftest import FakePhysioNet

from rain_pipeline import evidence, ledger, physio, provenance, replay
from rain_pipeline.errors import HoldoutViolation, ProtocolRefusal


def _quiet(_):
    pass


def test_a_replay_on_the_same_code_reproduces_every_value(completed):
    receipt = replay.replay("V3D-EXP-0001", layout=completed.layout, write=False, log=_quiet)
    comparison = receipt["comparison"]
    assert receipt["outcome"] == "reproduced"
    assert comparison["report"]["identical"] and comparison["data_identical"]
    assert all(m["identical"] for m in comparison["measurements"].values())
    assert comparison["status"] == {"recorded": "passed", "replayed": "passed"}
    assert receipt["replayed"]["result_sha256"] == provenance.sha256_file(
        completed.layout.experiments / "V3D-EXP-0001" / "runs" / "RUN-0001" / "result.json")


def test_a_replay_writes_nothing_but_its_receipt(completed):
    before = {p: p.read_bytes() for p in completed.root.rglob("*") if p.is_file() and ".git" not in p.parts
              and "replays" not in p.parts and "cache" not in p.parts}
    receipt = replay.replay("V3D-EXP-0001", layout=completed.layout, log=_quiet)
    after = {p: p.read_bytes() for p in before}
    assert before == after  # registry, ledger, runs: untouched
    written = completed.layout.resolve(receipt["path"])
    assert json.loads(written.read_text(encoding="utf-8"))["outcome"] == "reproduced"
    assert evidence.verify(completed.layout).ok


def test_two_replays_in_the_same_second_keep_both_receipts(completed):
    first = replay.replay("V3D-EXP-0001", layout=completed.layout, log=_quiet)["path"]
    second = replay.replay("V3D-EXP-0001", layout=completed.layout, log=_quiet)["path"]
    assert first != second


def test_substituted_data_is_an_error_not_a_reproduction(completed):
    (cached,) = [p for p in (completed.layout.cache).glob("syn01_*.dat")]
    data = bytearray(cached.read_bytes())
    data[100] ^= 0xFF                               # one flipped byte in the cached copy
    cached.write_bytes(bytes(data))
    receipt = replay.replay("V3D-EXP-0001", layout=completed.layout, write=False, log=_quiet)
    assert receipt["outcome"] == "error"
    assert "content differs from the first read" in receipt["comparison"]["error"]["message"]


def test_a_failed_replay_says_where_it_failed(completed, monkeypatch):
    for path in completed.layout.cache.glob("*.dat"):
        path.unlink()                               # force a fetch...
    server = FakePhysioNet()
    server.fail = "physionet.org unreachable"       # ...that cannot happen
    monkeypatch.setattr(physio, "_get", server.get)
    receipt = replay.replay("V3D-EXP-0001", layout=completed.layout, write=False, log=_quiet)
    assert (receipt["outcome"], receipt["comparison"]["error"]["stage"]) == ("error", "data")


def test_a_replay_never_reads_unseen_bytes(completed):
    book = ledger.load(completed.layout.ledger)
    book["entries"] = book["entries"][1:]           # as if one range had never been read by a run
    ledger.save(completed.layout.ledger, book)
    with pytest.raises(HoldoutViolation, match="never read by a run"):
        replay.replay("V3D-EXP-0001", layout=completed.layout, write=False, log=_quiet)


def test_only_completed_runs_can_be_replayed(completed):
    with pytest.raises(ProtocolRefusal, match="not recorded"):
        replay.replay("V3D-EXP-0001", run="RUN-0009", layout=completed.layout, write=False, log=_quiet)


@pytest.mark.parametrize("change, outcome", [
    (lambda c: None, "reproduced"),
    (lambda c: c["series"][next(iter(c["series"]))].update(identical=False), "measurements-reproduced"),
    (lambda c: c["report"].update(identical=False), "measurements-reproduced"),
    (lambda c: c["measurements"]["windows_analyzed"].update(identical=False), "verdict-reproduced"),
    (lambda c: c["status"].update(replayed="failed"), "verdict-differs"),
    (lambda c: c.update(error={"stage": "data", "type": "X", "message": "y"}), "error"),
])
def test_outcomes_follow_from_the_comparison_alone(completed, change, outcome):
    receipt = replay.replay("V3D-EXP-0001", layout=completed.layout, write=False, log=_quiet)
    change(receipt["comparison"])
    assert evidence.outcome_of(receipt["comparison"]) == outcome
    assert outcome in evidence.OUTCOMES


def test_report_differences_are_located_and_measured():
    found, largest = replay._differences({"a": [1.0, {"b": 2.0}], "c": "x"}, {"a": [1.0, {"b": 2.0 + 1e-15}], "c": "x"})
    assert found == ["/a/1/b"] and 0 < largest < 1e-14
    assert replay._differences({"a": 1}, {"a": 1}) == ([], 0.0)
    assert replay._differences({"a": [1]}, {"a": [1, 2]})[0] == ["/a"]
