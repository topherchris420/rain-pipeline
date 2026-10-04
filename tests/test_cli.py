"""The command line: one clear line for a refusal, and an exit code that says which kind of outcome it was."""

import json
import shutil

import pytest
from conftest import holdout_changes

from rain_pipeline import __version__, pipeline
from rain_pipeline.__main__ import EXIT_BROKEN, EXIT_ERROR, EXIT_OK, EXIT_REFUSED, main


def cli(*args, capsys=None):
    code = main([str(a) for a in args])
    out = capsys.readouterr() if capsys else None
    return code, out


def test_version_and_help(capsys):
    with pytest.raises(SystemExit) as done:
        main(["--version"])
    assert done.value.code == 0 and capsys.readouterr().out.strip() == f"rain-pipeline {__version__}"
    with pytest.raises(SystemExit) as done:
        main(["--help"])
    assert done.value.code == 0 and "Exit codes:" in capsys.readouterr().out


def test_an_unknown_command_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as done:
        main(["conclude"])
    assert done.value.code == 2


def test_a_missing_spec_is_refused_in_one_line(workspace, capsys):
    code, out = cli("--root", workspace.root, "run", workspace.root / "specs" / "absent.json", capsys=capsys)
    assert code == EXIT_REFUSED
    assert out.err.startswith("refused: ") and "no such spec file" in out.err and "Traceback" not in out.err


def test_a_malformed_spec_lists_every_problem(workspace, capsys):
    path = workspace.spec("broken", data={"source": "elsewhere", "grid_hz": -1})
    code, out = cli("--root", workspace.root, "explore", path, capsys=capsys)
    assert code == EXIT_REFUSED
    assert "data.source" in out.err and "data.grid_hz" in out.err


def test_an_uncommitted_registration_is_refused(workspace, physionet, anna, capsys):
    spec = workspace.spec("coupling")
    pipeline.register(spec, layout=workspace.layout, log=lambda _: None)
    code, out = cli("--root", workspace.root, "run", spec, capsys=capsys)
    assert code == EXIT_REFUSED and "not committed" in out.err
    assert not workspace.layout.runs.exists()


def test_a_goalpost_move_is_refused_by_rain(workspace, physionet, anna, capsys):
    spec = workspace.spec("coupling")
    pipeline.register(spec, layout=workspace.layout, log=lambda _: None)
    workspace.commit()
    moved = json.loads(spec.read_text(encoding="utf-8"))
    moved["preregistration"]["criteria"]["success"][0]["value"] = 0.1
    spec.write_text(json.dumps(moved), encoding="utf-8")
    code, out = cli("--root", workspace.root, "run", spec, capsys=capsys)
    assert code == EXIT_REFUSED and out.err.startswith("refused by R.A.I.N.:") and "write-once" in out.err


def test_run_exit_codes_distinguish_outcomes_from_errors(workspace, physionet, anna, capsys):
    spec = workspace.spec("coupling")
    pipeline.register(spec, layout=workspace.layout, log=lambda _: None)
    workspace.commit()
    assert cli("--root", workspace.root, "run", spec, capsys=capsys)[0] == EXIT_OK      # passed
    physionet.fail = "unreachable"
    shutil.rmtree(workspace.layout.cache)
    assert cli("--root", workspace.root, "run", spec, capsys=capsys)[0] == EXIT_ERROR   # recorded as an error


def test_verify_exit_codes(completed, capsys):
    code, out = cli("--root", completed.root, "verify", capsys=capsys)
    assert code == EXIT_OK and "confirmatory" in out.out
    code, out = cli("--root", completed.root, "verify", "--json", capsys=capsys)
    report = json.loads(out.out)
    assert code == EXIT_OK and report["ok"] and report["claims"][0]["evidence_level"] == "confirmatory"
    (completed.layout.results).write_text("# edited\n", encoding="utf-8")
    assert cli("--root", completed.root, "verify", capsys=capsys)[0] == EXIT_BROKEN


def test_strict_verify_fails_when_history_cannot_be_checked(completed, capsys):
    shutil.rmtree(completed.root / ".git")
    assert cli("--root", completed.root, "verify", capsys=capsys)[0] == EXIT_OK
    assert cli("--root", completed.root, "verify", "--strict", capsys=capsys)[0] == EXIT_BROKEN


def test_replay_and_lineage(completed, capsys):
    code, out = cli("--root", completed.root, "replay", "V3D-EXP-0001", "--json", "--no-write", capsys=capsys)
    assert code == EXIT_OK and json.loads(out.out)["outcome"] == "reproduced"
    code, out = cli("--root", completed.root, "replay", "V3D-EXP-0042", capsys=capsys)
    assert code == EXIT_REFUSED and "V3D-EXP-0042 is not registered" in out.err
    code, out = cli("--root", completed.root, "lineage", "--json", capsys=capsys)
    graph = json.loads(out.out)
    assert code == EXIT_OK and len(graph["digest"]) == 64 and graph["claims"][0]["run_id"] == "V3D-EXP-0001-RUN-0001"


def test_publish_regenerates_the_results_page(completed, capsys):
    original = completed.layout.results.read_text(encoding="utf-8")
    completed.layout.results.write_text("# stale\n", encoding="utf-8")
    assert cli("--root", completed.root, "publish", capsys=capsys)[0] == EXIT_OK
    assert completed.layout.results.read_text(encoding="utf-8") == original


def test_holdout_with_allow_uncommitted_is_refused(workspace, physionet, anna, clean_code, capsys):
    spec = workspace.spec("coupling", **holdout_changes())
    pipeline.register(spec, layout=workspace.layout, log=lambda _: None)
    code, out = cli("--root", workspace.root, "run", spec, "--allow-uncommitted", capsys=capsys)
    assert code == EXIT_REFUSED and "holdout" in out.err
    assert not physionet.range_requests()
