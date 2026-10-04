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

## Results

| experiment | question | data | verdict (assigned by R.A.I.N.) |
|---|---|---|---|
| [V3D-EXP-0001](runs/20261004T150406Z/REPORT.md) | Does DRR recover respiration → heart-rate coupling at rest? | 20 people × 10 min | **PASSED**: 18 of 20 detected; 1 of 20 mismatched pairs |
| [V3D-EXP-0002](runs/20261004T174209Z/REPORT.md) | Do slow breathers escape a 3 s lag window, and does 6 s recover them? | held out: 190 windows | **FAILED** (F1): nothing to recover; 3 s already detected 33 of 33 slow windows |
| [V3D-EXP-0003](runs/20261004T181106Z/REPORT.md) | Can the lag window come from the breathing rhythm (half its period)? | held out: 190 windows | **PASSED**, at ceiling: matches both fixed windows (100%); mismatched 3 of 190 |

![V3D-EXP-0003: detection by breathing stratum and frequency, for three lag windows](runs/20261004T181106Z/figure.png)

### What the held-out data says

V3D-EXP-0001 missed two people, f2y09 and f2y10, who both breathe slowly. That suggested the 3 s lag window was too short for slow breathing. Two experiments tested this on 6,000 s per person that had never been read, with their criteria pushed to GitHub (`4b4a030`) before the first byte was fetched. The idea did not survive:

- **The coupling is too strong to miss in 10 minutes.** Within a person, breathing and heart rate correlate at a median |r| of 0.53, against 0.055 for mismatched people. Under the 3 s window, 171 of 190 windows reach the smallest p-value 199 surrogates allow (0.005), and none exceeds 0.020. Every lag window detects every window, including 43 windows breathing slower than the slow stratum (0.063–0.078 Hz).
- **So V3D-EXP-0002 fails, and V3D-EXP-0003's pass is weak.** The 6 s window had no gain to show. The breathing-derived window matching both fixed windows at 100% shows that it costs nothing. It does not show that it helps, because these windows could not tell the arms apart. Both outcomes stand as registered.
- **Truncation is real but rare.** *Description, not evidence.* In 6 of 76 slow or very slow windows, the 3 s window's best lag sat at its 3 s edge. The 6 s window found the true peak further out in 5 of them, with a lower p-value. None changed a detection.
- **f2y09's miss looks like signal quality, not lag.** All 10 of its held-out windows fail the pre-registered beat QC (86–94% valid RR intervals). Its V3D-EXP-0001 window passed at 95.3%, just over the 95% bar, and showed almost no coupling (|r| 0.03). Noisy ECG or frequent ectopic beats would both do this; the band-pass detector cannot tell which. f2y10 is detected in all 10 held-out windows; its V3D-EXP-0001 window was the exception.
- **The exploration's warning did not replicate.** On seen data the 6 s window fired on 4 of 20 mismatched pairs. On held-out data each lag window fired on 3 of 190.

**Next experiment** (not yet registered): escape the ceiling, so the arms can disagree. Use shorter windows (about 2 min) and the older Fantasia cohort (f1o/f2o). Nobody has read any of its bytes, and its weaker age-related coupling lowers the ceiling. Choose the window length by exploring on the seen young-cohort data first. Separately, a beat detector that flags ectopic beats would show whether f2y09 can be analysed at all.

Earlier on V3D-EXP-0001: heart rate → respiration was also detected in 90% of records, as its pre-registered limitation predicted, so it shows coupling, not direction. Its first attempt (`runs/20261004T145937Z`) crashed before submitting and is kept with a `CRASHED.txt`.

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
