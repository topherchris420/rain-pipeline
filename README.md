# rain-pipeline

**Anna → R.A.I.N. → DRR**: one question becomes cited literature, a debated and pre-registered experiment, a real-data analysis with controls, and a verdict that no model and no pipeline code is allowed to assign.

```
question
  │
  ├─[1] Anna         ingest arXiv → hybrid search → citation-first summary
  │                  → anna-research-record/v1, SHA-256 sealed, every excerpt re-verified
  ├─[2] R.A.I.N.     offline panel (James, Jasmine, Luca, Elena) argues over Anna's sources
  ├─[3] R.A.I.N.     pre-register rain-experiment/v1 (write-once) ── before any data is read
  ├─[4] data         PhysioNet byte-range fetch, every byte hashed
  ├─[5] DRR          lead–lag tests + positive / null / mismatched-subject controls
  └─[6] R.A.I.N.     admit rain-experiment-submission/v1 (no status field)
                     → R.A.I.N. evaluates the criteria → re-verifies → RESULTS.md
```

Each stage calls the upstream code in-process at a recorded commit. Nothing is copied or forked. The vendored repos stay unmodified, and every run records whether they were dirty.

## First result

[`V3D-EXP-0001`](experiments/V3D-EXP-0001/experiment.json): *Does DRR recover respiration-to-heart-rate coupling (RSA) in resting young adults?* The verdict is **PASSED (supported)**. See [RESULTS.md](RESULTS.md) and [the run report](runs/20261004T150406Z/REPORT.md).

| | needs | observed |
|---|---|---|
| G1 records analyzed | ≥ 16 | 20 |
| G2 positive-control detection | ≥ 0.9 | 1.00 |
| G3 synthetic-null false positives | ≤ 0.15 | 0.05 |
| G4 mismatched-subject detection | ≤ 0.25 | 0.05 |
| **S1 coupling detection** | **≥ 0.8** | **0.90** (18/20) |
| F1 coupling detection | < 0.5 | — |

What it does **not** show, and what to test next:

- **Direction.** Heart rate → respiration is also detected in 90% of records. The pre-registered limitation predicted this: the two signals share one rhythm.
- **Slow breathers.** The two misses, f2y09 and f2y10, both breathe at about 0.11–0.13 Hz. f1y03 was detected only at the edge of the window (3 s). The pre-registered 3 s lag window may be too short for them. That idea needs its own registration with a new title; this registration can't change.
- **Shared spectral peak.** Heart rate's dominant spectral peak matches the breathing frequency in only 20% of records, because low-frequency power dominates the heart-rate spectrum. The coupling is still detected.

The first attempt (`runs/20261004T145937Z`) crashed in glue code after the analysis, before submitting, so R.A.I.N. has no record of it (see its `CRASHED.txt`). The re-run reused the unchanged registration and produced identical measurements.

## Setup (Windows, no Docker)

```bash
git clone --recurse-submodules https://github.com/topherchris420/rain-pipeline.git
cd rain-pipeline
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
uv pip install --python .venv/Scripts/python.exe --no-deps -e vendor/dynamic-resonance-rooting
```

Anna, R.A.I.N. and DRR are git submodules under `vendor/`. Each is pinned to the commit that produced the committed results (anna `064af91`, james_library `9c8811e`, DRR `862c4f7`). Each run also records the commits and whether they were dirty. Moving a submodule to a newer commit is a code change: re-run the experiment and commit the new run.

Anna needs PostgreSQL. `pgserver` bundles Postgres 16 + pgvector and runs it from `.pgdata/` only while a run is in progress.

## Run

```bash
.venv/Scripts/python.exe -m rain_pipeline run specs/cardiorespiratory.json
.venv/Scripts/python.exe -m rain_pipeline run specs/cardiorespiratory.json --offline
.venv/Scripts/python.exe -m rain_pipeline verify
.venv/Scripts/python.exe -m pytest
```

- **`run`:** the full pipeline. The first run ingests arXiv metadata and fetches about 14 MB from PhysioNet.
- **`--offline`:** reuses the Anna index and the cached data.
- **`verify`:** R.A.I.N. re-derives every stored result, and each Anna record's fingerprint is re-checked.
- **`pytest`:** 15 offline tests.

Exit codes for `run`: 0 for passed, failed or inconclusive (all recorded outcomes), 3 for an `error` run.

## Writing a new experiment

Copy `specs/cardiorespiratory.json` and edit it:

- **`literature`:** the arXiv queries and the Anna search.
- **`data` / `analysis`:** what will run. These become the registration's `parameters`.
- **`preregistration`:** the R.A.I.N. definition (hypothesis, metrics, guards, success and failure criteria).

`drr_stage.py` must emit exactly the declared metrics, or the run is refused.

Registrations are **write-once**. If a spec no longer matches its stored registration, the pipeline refuses to run. Give it a new title to register a new experiment.

## Outputs per run (`runs/<UTC time>/`)

| file | from |
|---|---|
| `anna_record.json`, `anna_verification.json` | Anna research record packet + excerpt re-verification |
| `corpus/`, `panel_meeting.md`, `panel_summary.json` | R.A.I.N. panel over Anna's sources |
| `drr_report.json` | per-subject DRR statistics, controls, dataset byte ranges and hashes |
| `submission.json` | what R.A.I.N. was given (no status) |
| `REPORT.md`, `summary.json` | R.A.I.N.'s verdict, criteria table, literature, limitations |

R.A.I.N.'s own records are in `experiments/V3D-EXP-*/runs/` and `RESULTS.md`, which is generated and not to be edited by hand.

## Honest boundaries

- **The panel is R.A.I.N.'s offline mode.** The quotes are verbatim and verified, but the reasoning text is scripted. It informs the pre-registration and never writes criteria.
- **Anna uses its deterministic hashing embeddings.** That is lexical retrieval over arXiv metadata and abstracts, not semantic search. Install Anna's `requirements-engine.txt` for real embeddings; that path is untested here.
- **Experiment IDs are local to this repo.** R.A.I.N. numbers experiments per registry, so this repo's `V3D-EXP-0001` is a different experiment from `V3D-EXP-0001` in james_library's own ledger. Cite them as `rain-pipeline/V3D-EXP-0001`. This experiment will not be moved into R.A.I.N.'s ledger: a new registration there would postdate the results, which defeats pre-registration. Future experiments can go to R.A.I.N.'s ledger with `--registry <james_library checkout>/experiments`; register them before running.

## Data citation

PhysioNet Fantasia Database 1.0.0, ODC-By 1.0.

- Iyengar N, Peng C-K, Morin R, Goldberger AL, Lipsitz LA. Age-related alterations in the fractal scaling of cardiac interbeat interval dynamics. *Am J Physiol* 1996;271:R1078–R1084.
- Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. *Circulation* 2000;101(23):e215–e220.
