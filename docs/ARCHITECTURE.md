# Architecture

`rain-pipeline` is an evidence pipeline, not an analysis script. The path from question to verdict is explicit, and every step leaves a record that a later step, or a stranger, can check. The design goal is that the boundaries between *noticed*, *registered*, *measured* and *supported by the registered criteria* cannot be crossed by accident through the normal interface, and cannot be crossed quietly at all.

## Roles: who may decide what

| component | role | may decide | may never |
|---|---|---|---|
| Anna (`vendor/anna`) | retrieves and cites literature; seals the record | which sources were found | write criteria; judge a result |
| R.A.I.N. panel (`vendor/james_library`, offline mode) | argues over Anna's sources | what the literature does and does not say | write criteria; judge a result |
| researcher | writes the spec | the question, data, analysis and criteria, **before** the data | change any of them after registration |
| R.A.I.N. registry | stores the write-once definition; evaluates | the verdict (`rain-criteria/v1`), from registered criteria and submitted measurements only | accept a status from the runner |
| DRR (`vendor/dynamic-resonance-rooting`) | lagged correlation, surrogates, family-wise correction | numbers | interpret them |
| `rain_pipeline` | glue: reads data, runs studies, records, verifies | nothing about the hypothesis | assign a status; submit an unregistered metric; read unseen data outside a registered run |

The runner's submission has no status field; R.A.I.N.'s submission schema rejects one. The verdict is computed by R.A.I.N.'s `evaluate`, re-derived by R.A.I.N.'s `verify`, and graded for evidential strength by `evidence.verify`, which reads the R.A.I.N. record but never changes it.

## Modules

```
rain_pipeline/
  __main__.py      command line; refusals -> one line + exit 2
  pipeline.py      explore / register / run orchestration, REPORT.md
  spec.py          spec structure and registration policy (refuse before work)
  drr_stage.py     studies (rsa_coupling, lag_window) and their contracts: settings, outputs, dry run
  physio.py        PhysioNet Fantasia: WFDB headers, byte-range reads, R peaks, paired series
  anna_stage.py    Anna in-process on embedded PostgreSQL; sealed, re-verified record
  panel_stage.py   R.A.I.N. offline panel over Anna's sources; corpus fingerprint
  registry_stage.py R.A.I.N. registry: draft, find (write-once), anchor, submit, publish
  ledger.py        the data ledger: first reads, holdout arithmetic, append-only check
  evidence.py      verify: every link of the chain; claims and evidence levels; the evidence graph
  replay.py        re-execute a recorded run from its registration; receipts
  provenance.py    hashes, deterministic JSON, code identity, git history queries
  vendor.py        locate the pinned submodules; their commits, dirtiness and pins
  layout.py        where each kind of record lives
  errors.py        refusals (ProtocolRefusal and its kinds)
  figures.py       the lag-window figure (presentation, never evidence)
```

Dependencies point one way: `__main__` → `pipeline`, `replay`, `evidence` → stages → `provenance`, `layout`, `errors`. `evidence` never imports `pipeline`; `replay` uses `pipeline`'s data reading so that a replay reads exactly the way a run did.

## The chain

```
spec ── registration ── anchor commit                    criteria written, then timestamped by git
            │ binds (SHA-256): Anna record, panel corpus, parent result, exploration report,
            │                  holdout ranges, the ledger as it was
            ▼
data ranges (ledger) ──► run ──► artifacts               measured; every byte and file hash-bound
                          │
                          ▼
                   R.A.I.N. verdict                      the registered criteria, applied by R.A.I.N.
                          ▲
                   replay receipts                       re-executed from the registration, compared
```

`python -m rain_pipeline lineage --json` exports this as a graph. Nodes are registrations, runs, verdicts, data ranges, files, commits, code digests, explorations and receipts, each with its content hash. Edges are typed: `tests`, `evaluates`, `consumed`, `produced`, `binds`, `reserves`, `follows`, `motivated_by`, `anchored_by`, `executed`, `specified_by`, `replays`. The graph's `digest` (canonical SHA-256 of nodes and edges) identifies the evidence state. It changes when any record or bound file changes, and not when code or prose changes. See [EVIDENCE.md](EVIDENCE.md).

## Invariants

Each invariant is enforced at the point where it could be broken, re-checked by `verify`, and pinned by tests.

| invariant | enforced by | re-checked by `verify` | tests |
|---|---|---|---|
| Exploration reads only seen bytes and is never evidence | `explore` refuses unseen bytes and holdout specs; checks the ledger, never writes it; label `EXPLORATORY` | `exploration.label`, `exploration.data`, `ledger.accounted` | `test_pipeline_rules`, `test_evidence` |
| A holdout is unseen when registered | `register` refuses a holdout with any byte ever read | `holdout.before_registration`, `holdout.ledger_snapshot` | `test_pipeline_rules`, `test_protocol` |
| A holdout is unseen when anchored | `run` waits until reads are provably after the anchor; submits `holdout_bytes_read_before_anchor` for a registered guard | `holdout.before_anchor` | `test_protocol::test_a_read_between_registration_and_anchor_fails_the_guard` |
| A holdout is read once, by an anchored run on committed code | `run` refuses `--allow-uncommitted` and unpinned code for a holdout | `run.anchor`, `run.code` | `test_protocol` |
| Registrations are write-once | R.A.I.N. creates with `open("x")`; `find` refuses a drifted spec; `anchor` refuses a registration edited in history | `registration.history`, `registration.spec`, `framing.manifest`, `rain.verify` | `test_registry_stage`, `test_protocol`, `test_evidence` |
| Criteria precede data | `run` requires the first commit holding the registration; anchor time is ordered conservatively; the run records whether the anchor was pushed | `run.anchor`, `run.timing`, `run.published` | `test_registry_stage`, `test_protocol` |
| The runner never decides | the submission has no status; R.A.I.N. evaluates | `rain.verify` re-derives every status | `test_registry_stage::test_a_status_in_the_submission_is_refused` |
| Only registered metrics are evidence | `select_measurements`; registration refuses unproducible metrics; reports separate evaluated, described and unregistered outputs | `run.submission` | `test_protocol`, `test_spec` |
| Every run that read data has a record | every stage after the first read is inside the error path; rejected submissions and Ctrl-C become `error` runs | `ledger.accounted`, `runs.unrecorded` | `test_protocol` (six crash paths) |
| Records are what was submitted | R.A.I.N. builds the record from the submission | `run.submission` (hash and field-by-field) | `test_evidence` |
| Artifacts and framing are what was bound | SHA-256 recorded at creation | `run.artifacts`, `framing.files`, `framing.anna`, `framing.corpus`, `lineage.*` | `test_evidence` |
| The ledger only grows | atomic, locked writes; no rewrite API | `ledger.history` (every committed version) | `test_ledger`, `test_evidence` |
| The data is the data | each read hashed; exact re-reads must match the first read | `run.data`; `replay` re-hashes every byte | `test_replay::test_substituted_data_is_an_error_not_a_reproduction` |
| The code is known | runs record source digest, per-module hashes, git state, submodule pins | `run.code` resolves the digest to a commit | `test_provenance` |
| The results page is the registry | generated by `publish` | `results.page` | `test_evidence`, `test_cli` |
| Measured runs reproduce | studies are seeded per test; parallel and serial runs agree | receipts: `receipt.binding` | `test_drr_stage`, `test_replay`, `test_reproduce` |

## Trust boundaries

- **Data authority** is the external source and the bytes actually consumed. The ledger records each range's SHA-256 on first read; a re-read that hashes differently is refused ("the source changed").
- **Analytic authority** is DRR and this package at recorded commits. A holdout run must use committed, pinned code, so the code that produced it stays in history.
- **Epistemic authority** is R.A.I.N.'s registered criteria and evaluation, and nothing else.
- **Temporal authority** is git: the first commit holding a registration. Times are the committing machine's clock. Pushed history (GitHub) is the only externally witnessed time.

What the pipeline cannot see: reads made outside it, a machine clock set wrong at both registration and run time, and a writer who rewrites files and git history together. These are stated in the README's honest boundaries and in every holdout registration's limitations.

## Why this shape

A calculation is cheap. What is expensive is the provenance and discipline that make a reader trust it. Here, that discipline is code paths that refuse. The useful unit of output is not a notebook or a figure. It is a **replayable claim with lineage**: a verdict whose criteria, data, code and timing can each be re-derived from the repository by someone who does not trust the author.
