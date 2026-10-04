"""Command line: ``python -m rain_pipeline <command>``.

  explore SPEC      try an analysis on data the ledger has already seen (never evidence)
  register SPEC     Anna -> R.A.I.N. panel -> write-once registration; then commit and push
  run SPEC          data -> DRR -> R.A.I.N. verdict; refuses an unanchored registration
  verify            re-derive every result; re-check every link of the evidence chain
  replay EXP-ID     re-execute a recorded run from its registration; write a receipt
  lineage           the evidence chain behind every claim (--json: the evidence graph)
  publish           regenerate RESULTS.md from the registry

Exit codes:
  0  done: a recorded outcome (passed, failed or inconclusive), a clean verify,
     or a replay whose registered measurements reproduced
  1  verify found a broken link, or a replay's measurements or verdict differ
  2  refused: nothing was read, registered or recorded (the message says why)
  3  a run or replay was recorded as an error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, evidence, pipeline, registry_stage
from . import replay as replays
from .errors import ProtocolRefusal
from .layout import Layout

EXIT_OK, EXIT_BROKEN, EXIT_REFUSED, EXIT_ERROR = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rain_pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"rain-pipeline {__version__}")
    parser.add_argument("--root", type=Path, default=None,
                        help="evidence repository to work on (default: $RAIN_PIPELINE_ROOT, else this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)

    explore = sub.add_parser("explore", help="exploratory analysis on already-seen data")
    explore.add_argument("spec", type=Path)

    register = sub.add_parser("register", help="frame and pre-register an experiment")
    register.add_argument("spec", type=Path)
    register.add_argument("--offline", action="store_true", help="skip arXiv ingestion; search the existing Anna index")

    run = sub.add_parser("run", help="run a registered experiment")
    run.add_argument("spec", type=Path)
    run.add_argument("--allow-uncommitted", action="store_true",
                     help="run although the registration is not committed to git (weakens the evidence; "
                          "refused for a holdout)")

    verify = sub.add_parser("verify", help="re-derive stored results and re-check the evidence chain")
    verify.add_argument("--json", action="store_true", help="print the full report as JSON")
    verify.add_argument("--strict", action="store_true",
                        help="also fail when a check cannot run (for CI: requires full git history)")

    replay = sub.add_parser("replay", help="re-execute a recorded run and compare it with the record")
    replay.add_argument("experiment_id")
    replay.add_argument("--run", help="RUN-NNNN (default: the latest completed run)")
    replay.add_argument("--no-write", action="store_true", help="print the outcome without writing a receipt")
    replay.add_argument("--json", action="store_true", help="print the receipt as JSON")

    lineage = sub.add_parser("lineage", help="the evidence chain behind every claim")
    lineage.add_argument("--json", action="store_true", help="print the evidence graph and claims as JSON")

    sub.add_parser("publish", help="regenerate RESULTS.md from the registry")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # agents quote Unicode; cp1252 consoles choke
    args = _parser().parse_args(argv)
    layout = Layout.at(args.root) if args.root else Layout.default()
    try:
        return _dispatch(args, layout)
    except ProtocolRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:
        if isinstance(exc, registry_stage.experiment_error()):  # R.A.I.N. would not accept it
            print(f"refused by R.A.I.N.: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        raise


def _dispatch(args: argparse.Namespace, layout: Layout) -> int:
    if args.command == "explore":
        pipeline.explore(args.spec, layout=layout)
        return EXIT_OK
    if args.command == "register":
        pipeline.register(args.spec, offline=args.offline, layout=layout)
        return EXIT_OK
    if args.command == "run":
        summary = pipeline.run(args.spec, layout=layout, allow_uncommitted=args.allow_uncommitted)
        return EXIT_ERROR if summary["status"] == "error" else EXIT_OK
    if args.command == "replay":
        receipt = replays.replay(args.experiment_id, run=args.run, layout=layout, write=not args.no_write,
                                 log=(lambda _: None) if args.json else print)
        if args.json:
            print(json.dumps(receipt, indent=2, ensure_ascii=False))
        elif "path" in receipt:
            print(f"Receipt: {receipt['path']}")
        return {"reproduced": EXIT_OK, "measurements-reproduced": EXIT_OK,
                "error": EXIT_ERROR}.get(receipt["outcome"], EXIT_BROKEN)
    if args.command == "lineage":
        report, graph = evidence.verify(layout), evidence.graph(layout)
        if args.json:
            print(json.dumps({**graph, "claims": report.claims}, indent=2, ensure_ascii=False))
        else:
            print(evidence.describe(report, graph))
        return EXIT_OK
    if args.command == "publish":
        print(f"Wrote {layout.relative(pipeline.publish(layout=layout))}")
        return EXIT_OK

    report = evidence.verify(layout)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(evidence.render_checks(report))
    failed = not report.ok or (args.strict and report.counts()["skip"] > 0)
    return EXIT_BROKEN if failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
