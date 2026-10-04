"""Where an evidence repository keeps each kind of record.

One ``Layout`` names every path the protocol reads or writes. The default is
the repository this package ships in (or ``RAIN_PIPELINE_ROOT``); tests and
other evidence repositories point the whole protocol somewhere else with
``Layout.at(root)``.

    specs/              human-written intent (experiment and exploration specs)
    explorations/       exploratory reports on seen data; never evidence
    framing/<spec>/     literature, panel and binding manifest, fixed at registration
    experiments/        R.A.I.N.'s registry: write-once registrations and run records
    RESULTS.md          R.A.I.N.'s results page, generated from experiments/
    runs/<UTC time>/    what each run submitted, its artifacts and its report
    replays/            reproducibility receipts: a recorded run re-executed and compared
    data/ledger.json    every byte range ever read, with the time and reader of its first read
    data/cache/         downloaded bytes (not committed; re-fetchable and hash-checked)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
CODE_ROOT = PACKAGE_DIR.parent  # the repository this package's source lives in


@dataclass(frozen=True)
class Layout:
    root: Path
    specs: Path
    explorations: Path
    framing: Path
    experiments: Path
    results: Path
    runs: Path
    replays: Path
    ledger: Path
    cache: Path

    @classmethod
    def at(cls, root: str | Path) -> "Layout":
        root = Path(root).resolve()
        return cls(
            root=root,
            specs=root / "specs",
            explorations=root / "explorations",
            framing=root / "framing",
            experiments=root / "experiments",
            results=root / "RESULTS.md",
            runs=root / "runs",
            replays=root / "replays",
            ledger=root / "data" / "ledger.json",
            cache=root / "data" / "cache" / "fantasia",
        )

    @classmethod
    def default(cls) -> "Layout":
        """``$RAIN_PIPELINE_ROOT``, else the checkout this package runs from, else the working directory.

        The last case is a non-editable install, whose package directory holds no records.
        """
        if os.environ.get("RAIN_PIPELINE_ROOT"):
            return cls.at(os.environ["RAIN_PIPELINE_ROOT"])
        if (CODE_ROOT / "experiments").is_dir() or (CODE_ROOT / "specs").is_dir():
            return cls.at(CODE_ROOT)
        return cls.at(Path.cwd())

    def with_roots(self, *, registry_root: Path | None = None, runs_root: Path | None = None,
                   framing_root: Path | None = None, explorations_root: Path | None = None,
                   data_root: Path | None = None, replays_root: Path | None = None) -> "Layout":
        """The keyword roots the 0.2 API accepted, mapped onto a layout."""
        changes: dict[str, Path] = {}
        if registry_root is not None:
            changes.update(experiments=Path(registry_root), results=Path(registry_root).parent / "RESULTS.md")
        if runs_root is not None:
            changes["runs"] = Path(runs_root)
        if framing_root is not None:
            changes["framing"] = Path(framing_root)
        if explorations_root is not None:
            changes["explorations"] = Path(explorations_root)
        if replays_root is not None:
            changes["replays"] = Path(replays_root)
        if data_root is not None:
            changes.update(ledger=Path(data_root) / "ledger.json", cache=Path(data_root) / "cache" / "fantasia")
        return replace(self, **changes)

    def relative(self, path: Path) -> str:
        """``path`` relative to the repository root, in POSIX form (its name if it lies outside)."""
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return Path(path).name

    def resolve(self, relative: str) -> Path:
        """A repository-relative POSIX path recorded in a manifest, as a path on disk."""
        return self.root / Path(*relative.split("/"))


def resolve(layout: Layout | None, roots: dict[str, Path | None]) -> Layout:
    """The layout a public function should use: explicit, else default, plus any legacy roots."""
    base = layout or Layout.default()
    given = {k: v for k, v in roots.items() if v is not None}
    unknown = set(given) - {"registry_root", "runs_root", "framing_root", "explorations_root", "data_root",
                            "replays_root"}
    if unknown:
        raise TypeError(f"unexpected keyword argument(s): {', '.join(sorted(unknown))}")
    return base.with_roots(**given) if given else base
