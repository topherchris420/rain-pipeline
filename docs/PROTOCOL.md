# Experimental protocol

The operating contract for extending `rain-pipeline` without weakening its evidence. Most rules here are enforced by code that refuses; the rest are checked by `verify`. Where a rule is only a convention, it says so.

## Lifecycle

### 1. Explore (observation, never evidence)

`python -m rain_pipeline explore specs/<exploration>.json` runs a study on data the ledger has **already seen**. Use it to choose window lengths, QC thresholds, controls and candidate statistics, and to find implementation failures.

- Enforced: any unseen byte is refused, and so is a spec that declares a holdout. Exploration checks the ledger and never writes to it.
- Enforced: the report is labelled `EXPLORATORY … It is not evidence for any claim`. `verify` checks the label and that every byte was seen before the exploration ran.
- Convention: describe exploratory results as description in prose, never as confirmation.

### 2. Register (criteria, before data)

Write a spec (see the README) under a **new file name** and run `python -m rain_pipeline register specs/<name>.json`. A registration states, before the confirmation data is read: the question, hypothesis, dataset and exact segments, analysis settings, seed, guards, success and failure criteria, limitations, and optionally its lineage (a prior run, the exploration that motivated it).

`register` refuses, **before any literature search or data access**, when:

- the spec is malformed (every problem is listed at once);
- R.A.I.N. would reject the definition (e.g. a criterion on an undeclared metric);
- a registered metric is one the study never produces with these settings;
- the analysis fails a dry run on synthetic data;
- a declared holdout has no guard requiring zero early reads (`holdout_bytes_read_before_anchor <= 0`, or `…_before_registration`);
- any byte of the holdout was ever read;
- the holdout overlaps one already reserved by another registration, unless `data.holdout_shared_with` names it;
- `framing/<spec>/` already holds another experiment's dossier;
- the lineage names a run that is not recorded, or an exploration report that is not one.

The registration binds by SHA-256 the Anna record, the panel corpus, the parent result, the exploration report and the ledger as it was. It is write-once.

### 3. Anchor (the timestamp)

Commit and push `experiments/`, `framing/`, `data/ledger.json` and `RESULTS.md`. The **first commit that holds the registration** is its anchor. Every later commit must hold the identical file, or the registration is anchored to nothing (`run` refuses; `verify` fails `registration.history`).

- Never amend, rebase or squash a registration commit. Rewriting it moves the anchor and erases the timestamp it carried.
- Do not use `--allow-uncommitted` for evidence intended to support a public claim. It exists for development; it is refused for a holdout.

### 4. Run (measurement)

`python -m rain_pipeline run specs/<name>.json`. The runner:

1. refuses if the registration is missing, drifted from its spec, uncommitted, or changed in history, or if the framing dossier no longer matches its bindings;
2. for a holdout, refuses uncommitted or unpinned code, and waits until its reads are provably later than the anchor (git records whole seconds);
3. dry-runs the analysis (an environment that cannot run it is refused before any read);
4. plans exact byte ranges, reads them, and logs each first read in the ledger;
5. applies the registered QC, computes the registered study, and selects exactly the registered metrics;
6. adds `holdout_bytes_read_before_registration` and `holdout_bytes_read_before_anchor` for R.A.I.N. to judge;
7. writes `drr_report.json` and the figure, then submits measurements **without a status**.

Every failure after the run starts is filed by R.A.I.N. as an `error` run, never lost. That covers data, analysis, artifacts, a rejected submission (kept as `submission.rejected.json`), a failure assembling the submission, and Ctrl-C (recorded, then re-raised). A non-finite measurement is submitted as not measured. A figure that fails to render is noted and does not void the run.

### 5. Evaluate (R.A.I.N. alone)

R.A.I.N. applies `rain-criteria/v1` to the submitted measurements:

| status | verdict | when |
|---|---|---|
| `inconclusive` | `insufficient_evidence` | a guard does not hold, or cannot be evaluated |
| `failed` | `not_supported` | a failure criterion holds (failure dominates success) |
| `passed` | `supported` | every success criterion holds and no failure criterion does |
| `inconclusive` | `insufficient_evidence` | otherwise (including a success criterion on a missing measurement) |
| `error` | `not_evaluated` | the run could not complete; this is not a failed hypothesis |

These outcomes are not collapsed into success and failure. A failed or inconclusive result is a result.

### 6. Verify (audit)

`python -m rain_pipeline verify` re-derives every link of the chain. The checks are listed in [EVIDENCE.md](EVIDENCE.md#what-verify-checks). CI runs it with `--strict` on full history for every push and pull request.

When verify fails, do not edit the record to make it pass. Find what changed, restore it from git, or record the change honestly; a broken chain is itself information. Warnings are for honest weaknesses (an unanchored historical registration, an unrecorded attempt); they stay visible.

### 7. Replay (reproduction)

`python -m rain_pipeline replay V3D-EXP-NNNN` re-executes a recorded run from its registration and writes a receipt to `replays/`. Commit receipts: each is a dated, environment-stamped reproducibility claim that `verify` keeps honest. Replay after moving a submodule pin or a numeric dependency, and before relying on results produced under the new environment.

## Design rules

### Do

- Preserve seeds, controls, QC exclusions, raw records and negative results.
- Keep provenance next to outputs; keep external repositories pinned.
- Add a test for every new evidence invariant, and make it fail on the violation it guards against.
- Make new experiments additive: a new idea gets a new title, a new spec file and a new registration.
- Name the multiplicity: experiments judged on the same holdout acknowledge each other in `data.holdout_shared_with` and in their limitations.
- Distinguish new data from new subjects in the hypothesis and limitations; `lineage` reports which records earlier experiments analysed.

### Do not

- Add a status field to a submission, or let the runner decide a verdict (R.A.I.N. rejects it).
- Read holdout data in exploration, or with `--allow-uncommitted` (refused).
- Edit a registration, its spec, its framing dossier or the ledger after the fact (refused by `run`, failed by `verify`).
- Delete failed, inconclusive or crashed runs (`verify` lists unrecorded attempts).
- Treat a higher correlation, a lower p-value or a prettier figure as a reason to change criteria.
- Hand-edit `RESULTS.md` (`verify` compares it with the registry; regenerate with `publish`).

## Adding a study

A study lives in `drr_stage.py` and is published as a `Study` contract:

1. `run(windows, excluded, analysis) -> DrrResult`: measurements, series and a report. It must be deterministic given the seed. Seed each test on its own so results do not depend on scheduling.
2. `problems(analysis) -> list[str]`: every reason the settings cannot run, including unknown keys.
3. `outputs(analysis) -> list[str]`: exactly the measurements `run` emits, in order.

Registration then refuses metrics the study cannot produce, and the dry run proves `run` emits exactly `outputs`. Provide controls where scientifically appropriate: at least one positive and one null, run with the real pairs' exact settings. Add tests for edge cases and a `test_a_study_emits_exactly_its_declared_outputs` case.

Changing an existing study's numerics changes what registered experiments measure. Replay every experiment that uses it; if a registered result no longer reproduces, that is a finding to report, not a reason to edit the record.

## Adding a data source

Only PhysioNet Fantasia exists today. A new source must:

- plan exact byte ranges from metadata alone, without reading signal bytes;
- read through the ledger hook (`on_read`), so each first read is logged with its SHA-256 and a re-read is checked against it;
- name records by a stable subject identity, so `lineage` can tell new data from new subjects;
- ship an offline double in `tests/conftest.py`, so the protocol tests exercise it end to end.

## Versioning

`rain_pipeline.__version__` is the only version. Every run records it and its source digest. Bump it for any change to what runs record or how they behave, and add a `CHANGELOG.md` entry. Historical runs keep the version they were produced with.
