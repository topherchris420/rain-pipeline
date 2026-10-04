"""Command line: ``python -m rain_pipeline run SPEC`` and ``python -m rain_pipeline verify``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import pipeline, registry_stage, vendor


def _verify(args: argparse.Namespace) -> int:
    registry = registry_stage.open_registry(Path(args.registry))
    report = registry_stage.verify(registry, args.experiment)
    print(json.dumps(report, indent=2))

    from engine import records  # importable once open_registry() set up the vendored paths

    status = 0 if report["valid"] else 1
    for packet_path in sorted(Path(args.runs).glob("*/anna_record.json")):
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        result = records.verify_record(packet, None)  # offline: fingerprint only
        ok = result["fingerprint"]["matches"]
        print(f"{packet_path.parent.name}: Anna record fingerprint {'MATCH' if ok else 'MISMATCH'}")
        status |= 0 if ok else 1
    return status


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # agents quote Unicode; cp1252 consoles choke
    root = vendor.PROJECT_ROOT
    parser = argparse.ArgumentParser(prog="python -m rain_pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the full Anna -> R.A.I.N. -> DRR pipeline for one spec")
    run.add_argument("spec", type=Path)
    run.add_argument("--offline", action="store_true", help="skip arXiv ingestion; search the existing Anna index")
    run.add_argument("--registry", type=Path, default=root / "experiments",
                     help="R.A.I.N. registry directory (RESULTS.md is written next to it)")

    check = sub.add_parser("verify", help="re-derive stored R.A.I.N. results and re-check Anna fingerprints")
    check.add_argument("--registry", default=str(root / "experiments"))
    check.add_argument("--runs", default=str(root / "runs"))
    check.add_argument("--experiment", help="limit R.A.I.N. verification to one experiment id")

    args = parser.parse_args(argv)
    if args.command == "verify":
        return _verify(args)
    summary = pipeline.run(args.spec, offline=args.offline, registry_root=args.registry)
    return {"passed": 0, "failed": 0, "inconclusive": 0}.get(summary["status"], 3)


if __name__ == "__main__":
    raise SystemExit(main())
