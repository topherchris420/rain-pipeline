# rain-pipeline

**Anna → R.A.I.N. → DRR**: one question becomes cited literature, a debated and pre-registered experiment, a real-data analysis with controls, and a verdict that no model and no pipeline code is allowed to assign.

```
            explore ── seen data only, never evidence ──┐  (hash bound into the registration)
                                                         ▼
question ──► register ── Anna: arXiv → hybrid search → cited summary, sealed + re-verified
                     ├── R.A.I.N. panel argues over Anna's sources
                     └── write-once rain-experiment/v1, binding literature, panel,
                         parent result, exploration and holdout proof by hash
         ──► git commit + push          ◄── the public timestamp: criteria before data
         ──► run ── refuses an uncommitted registration
                 ├── PhysioNet byte ranges, each logged in data/ledger.json
                 ├── DRR study: real pairs + mismatched-person + synthetic controls
                 └── submission with no status field → R.A.I.N. alone assigns the verdict
         ──► verify ── re-derives every result; re-checks every hash, binding and holdout
```

Each stage calls the upstream code in-process at a pinned commit. Nothing is copied or forked, and every run records whether the vendored repos were dirty.

<!-- RESULTS -->

## The protocol, and what each step guarantees

| step | command | guarantee |
|---|---|---|
| explore | `explore SPEC` | Reads only bytes the ledger has already seen; refuses anything else. Trying ideas can never spend a holdout. Output is labelled *not evidence*. |
| register | `register SPEC` | Refuses a declared holdout if any of its bytes were ever read. Writes a write-once registration that binds, by SHA-256, the Anna record, the panel corpus, the parent result and the exploration report. |
| commit | `git commit && git push` | The commit is the timestamp. GitHub shows the criteria existed before the data was read. |
| run | `run SPEC` | Refuses an uncommitted or edited registration. Logs every byte range it reads. Submits exactly the registered metrics, with no status. Reports the holdout bytes read before registration as a guard metric (must be 0). |
| verify | `verify` | R.A.I.N. re-derives every stored result. Every Anna fingerprint, framing binding and holdout claim is re-checked. |

Registrations never change. If a spec no longer matches its stored registration, `run` refuses; a changed idea needs a new title and a new registration. A crash after registration is recorded as an R.A.I.N. `error` run, distinct from a failed hypothesis.

The data ledger is a log kept by this tool. It makes the holdout claim checkable and prevents accidents; it cannot rule out reads made outside the pipeline.

## Setup (Windows, no Docker)

```bash
git clone --recurse-submodules https://github.com/topherchris420/rain-pipeline.git
cd rain-pipeline
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
uv pip install --python .venv/Scripts/python.exe --no-deps -e vendor/dynamic-resonance-rooting
```

Anna, R.A.I.N. and DRR are git submodules under `vendor/`, pinned to the commits that produced the committed results (anna `064af91`, james_library `9c8811e`, DRR `862c4f7`). Moving a submodule is a code change: re-run and commit the new runs.

Anna needs PostgreSQL. `pgserver` bundles Postgres 16 + pgvector and runs it from `.pgdata/` only while a command needs it.

## Commands

```bash
.venv/Scripts/python.exe -m rain_pipeline explore specs/explore-lag-window.json
.venv/Scripts/python.exe -m rain_pipeline register specs/<new-spec>.json
.venv/Scripts/python.exe -m rain_pipeline run specs/<registered-spec>.json
.venv/Scripts/python.exe -m rain_pipeline verify
.venv/Scripts/python.exe -m pytest
```

- `run` exits 0 for any recorded outcome (passed, failed, inconclusive) and 3 for an `error` run.
- DRR tests run in parallel across CPU cores; results are identical to a single process. `RAIN_PIPELINE_WORKERS=1` forces one process.
- `pytest` runs 28 offline tests. One of them replays V3D-EXP-0001 from the cached data and requires identical measurements; it is skipped on a fresh clone until the cache exists.

## Writing a new experiment

Copy a spec from `specs/` and edit it:

- **`literature`**: arXiv queries for Anna's index, and the search that becomes the cited record.
- **`lineage`** (optional): the result it follows (`V3D-EXP-NNNN/RUN-NNNN`), what was observed, and the exploration report.
- **`data`**: records, segments, QC. `"holdout": true` makes register and run enforce that the data is unseen.
- **`analysis`**: the DRR study (`rsa_coupling` or `lag_window`) and its settings. These become the registration's parameters.
- **`preregistration`**: the R.A.I.N. definition: hypothesis, metrics, guards, success and failure criteria, limitations.

Only metrics declared in the registration are submitted. Everything else a study computes stays in its report as description.

## Layout

| path | what |
|---|---|
| `specs/` | experiment and exploration specs |
| `explorations/` | exploratory reports and figures on seen data; never evidence |
| `framing/<spec>/` | Anna record, panel transcript and corpus, and `framing.json`, fixed at registration |
| `experiments/`, `RESULTS.md` | R.A.I.N.'s registry and its generated results page (do not edit by hand) |
| `runs/<UTC time>/` | `REPORT.md`, `figure.png`, `drr_report.json`, `submission.json`, `summary.json` |
| `data/ledger.json` | every byte range read, with the time and reader of its first read |

## Honest boundaries

- **The panel is R.A.I.N.'s offline mode.** Its quotes are verbatim and verified; its reasoning text is scripted. It informs the pre-registration and never writes criteria. When the retrieved abstracts do not address the question, it says so (grounding `none`), as it did for V3D-EXP-0002 and 0003.
- **Anna uses its deterministic hashing embeddings**: lexical retrieval over arXiv metadata and abstracts, not semantic search.
- **Experiment IDs are local to this repo.** R.A.I.N. numbers experiments per registry, so `rain-pipeline/V3D-EXP-0001` is not james_library's `V3D-EXP-0001`. Future experiments can go to R.A.I.N.'s own ledger with `--registry`; register them before running.
- **V3D-EXP-0001 predates the protocol.** It was registered before its data was fetched, but the registration was not committed before the run, and the ledger shows two of its 20 records (f1y01, f2y01) were first read by an R-peak dry check that computed no coupling statistic. Its framing files were copied into `framing/cardiorespiratory/` byte for byte.

## Data citation

PhysioNet Fantasia Database 1.0.0, ODC-By 1.0.

- Iyengar N, Peng C-K, Morin R, Goldberger AL, Lipsitz LA. Age-related alterations in the fractal scaling of cardiac interbeat interval dynamics. *Am J Physiol* 1996;271:R1078–R1084.
- Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. *Circulation* 2000;101(23):e215–e220.
