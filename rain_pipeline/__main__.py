"""Command line: ``python -m rain_pipeline {explore,register,run,verify}``.

  explore SPEC    try an analysis on data the ledger has already seen (never evidence)
  register SPEC   Anna -> R.A.I.N. panel -> write-once registration; then commit and push
  run SPEC        data -> DRR -> R.A.I.N. verdict; refuses an uncommitted registration
  verify          re-derive every stored result; re-check every hash and holdout
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import pipeline


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # agents quote Unicode; cp1252 consoles choke
    parser = argparse.ArgumentParser(prog="python -m rain_pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    explore = sub.add_parser("explore", help="exploratory analysis on already-seen data")
    explore.add_argument("spec", type=Path)

    register = sub.add_parser("register", help="frame and pre-register an experiment")
    register.add_argument("spec", type=Path)
    register.add_argument("--offline", action="store_true", help="skip arXiv ingestion; search the existing Anna index")

    run = sub.add_parser("run", help="run a registered experiment")
    run.add_argument("spec", type=Path)
    run.add_argument("--allow-uncommitted", action="store_true",
                     help="run although the registration is not committed to git (weakens the evidence)")

    sub.add_parser("verify", help="re-derive stored results and re-check hashes and holdouts")

    args = parser.parse_args(argv)
    if args.command == "explore":
        pipeline.explore(args.spec)
        return 0
    if args.command == "register":
        pipeline.register(args.spec, offline=args.offline)
        return 0
    if args.command == "run":
        summary = pipeline.run(args.spec, allow_uncommitted=args.allow_uncommitted)
        return 3 if summary["status"] == "error" else 0
    report = pipeline.verify()
    print(json.dumps(report["rain"], indent=2))
    for item in report["checks"]:
        print(f"{'ok  ' if item['ok'] else 'FAIL'}  {item['check']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
