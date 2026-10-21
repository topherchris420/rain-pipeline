"""This repository's own evidence verifies, and what its documents claim agrees with its records."""

import re
from importlib.metadata import PackageNotFoundError, version

import pytest

from rain_pipeline import __version__, evidence, physio, provenance
from rain_pipeline.layout import CODE_ROOT, Layout

README = (CODE_ROOT / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def report():
    return evidence.verify(Layout.default())


def test_the_committed_evidence_verifies(report):
    broken = [c for c in report.checks if c.status == evidence.FAIL]
    assert not broken, broken


def test_the_historical_claims_keep_their_honest_levels(report):
    levels = {c["experiment_id"]: c["evidence_level"] for c in report.claims}
    history = evidence.snapshot(Layout.default()).history
    if not history.available or history.shallow:
        pytest.skip("evidence levels need full git history")
    assert levels["V3D-EXP-0001"] == "registered"     # predates the protocol: never anchored before its run
    assert levels["V3D-EXP-0002"] == "confirmatory"
    assert levels["V3D-EXP-0003"] == "confirmatory"


def test_the_readme_results_table_states_what_rain_recorded(report):
    rows = re.findall(r"^\| \[(V3D-EXP-\d{4})\]\([^)]*\) \|[^|]*\|[^|]*\| \*\*(PASSED|FAILED|INCONCLUSIVE|ERROR)\*\*[^|]*"
                      r"\| (\w+)", README, flags=re.M)
    assert rows, "README has no results table"
    claims = {c["experiment_id"]: c for c in report.claims}
    for experiment_id, status, level in rows:
        assert claims[experiment_id]["status"].upper() == status, experiment_id
        if claims[experiment_id]["evidence_level"] != "unverified":
            assert claims[experiment_id]["evidence_level"] == level, experiment_id
    assert {r[0] for r in rows} == set(claims)  # every recorded experiment is in the table, and no other


def test_every_receipt_in_the_readme_exists_and_says_what_the_readme_says():
    cited = re.findall(r"\]\((replays/[^)]+\.json)\) \| `([a-z-]+)`", README)
    assert cited, "README cites no replay receipts"
    for path, outcome in cited:
        receipt = provenance.read_json(CODE_ROOT / path)
        assert receipt is not None, path
        assert receipt["outcome"] == outcome, path


def test_one_version_everywhere():
    pyproject = (CODE_ROOT / "pyproject.toml").read_text(encoding="utf-8")  # (tomllib is 3.11+; CI also runs 3.10)
    assert re.search(r'^dynamic = \["version"\]$', pyproject, flags=re.M)
    assert re.search(r'^version = \{attr = "rain_pipeline.__version__"\}$', pyproject, flags=re.M)
    assert not re.search(r'^version = "', pyproject, flags=re.M)
    try:
        assert version("rain-pipeline") == __version__
    except PackageNotFoundError:
        pass
    assert f"rain-pipeline/{__version__} " in physio.USER_AGENT
    changelog = (CODE_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## (\S+)", changelog, flags=re.M).group(1) == __version__


def test_docs_use_rains_outcome_vocabulary():
    for name in ("README.md", "docs/ARCHITECTURE.md", "docs/PROTOCOL.md", "docs/EVIDENCE.md"):
        text = (CODE_ROOT / name).read_text(encoding="utf-8")
        assert "contradicted" not in text and "unresolved" not in text, name  # not R.A.I.N. statuses


def test_the_readme_rehearsal_table_states_what_rehearse_derives():
    from rain_pipeline import rehearsal

    rows = re.findall(r"^\| (V3D-EXP-\d{4}) \| `([^`]+)` \| (passed|failed|inconclusive) \| ([\d,]+) of ([\d,]+) \|",
                      README, flags=re.M)
    assert rows, "README has no rehearsal table"
    layout = Layout.default()
    for experiment_id, exploration, status, recurs, resamples in rows:
        framing = next(p for p in layout.framing.glob("*/framing.json")
                       if provenance.read_json(p)["experiment_id"] == experiment_id)
        spec = layout.resolve(provenance.read_json(framing)["spec"])
        doc = rehearsal.rehearse_spec(spec, on=exploration, layout=layout, resamples=int(resamples.replace(",", "")))
        assert doc["observed"]["status"] == status, experiment_id
        assert doc["resampled"]["statuses"][status] == int(recurs.replace(",", "")), experiment_id


def test_the_window_length_figure_draws_from_the_committed_explorations(tmp_path):
    from rain_pipeline import figures

    reports = [provenance.read_json(p) for p in sorted(CODE_ROOT.glob("explorations/20261021T*/report.json"))]
    assert sorted(figures._window_seconds(r) for r in reports) == [60, 120, 300, 600]
    ref = figures.window_lengths(reports, tmp_path / "window-lengths.png")
    assert ref["bytes"] > 10_000 and (tmp_path / "window-lengths.png").read_bytes().startswith(b"\x89PNG")
    assert (CODE_ROOT / "docs" / "window-lengths.png").is_file() and "docs/window-lengths.png" in README
