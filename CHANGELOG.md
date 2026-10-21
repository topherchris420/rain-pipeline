# Changelog

Each run records the version and source digest of the code that produced it
(`inputs.code.pipeline`), and `verify` maps that digest back to the exact
commit. Historical runs keep the version they were produced with; a new
version never rewrites them.

## 0.4.0 — 2026-10-21

Preregistration proves when the criteria were written. 0.4.0 adds the second
question a reader should ask of every confirmatory verdict: could the data have
answered otherwise?

**Rehearsal (new)**

- `python -m rain_pipeline rehearse SPEC [--on EXPLORATION]` applies a spec's
  criteria, through R.A.I.N.'s evaluator, to an exploration of seen data. It
  reports the verdict data like that gives, how often the verdict recurs over
  1,000 resamples of the exploration's people (settled at 95%), which
  contrasts are blind (their arms decide every test alike, so they are 0 by
  construction), and which rival arms the criteria cannot tell apart from a
  registered one. It reads no data, runs no test and writes nothing.
  Guards on the design's size and criteria on the holdout metrics are set
  aside and listed; everything else is applied as registered.
- `register` rehearses on `lineage.exploration` as its third step, writes
  `framing/<spec>/rehearsal.json` and binds it by hash (`rehearsal_sha256`), so
  what the data could decide is anchored in the same commit as the criteria.
  An exploration of other tests is recorded as not rehearsable, with the reason.
- `verify` checks the bound rehearsal and derives it again (`framing.rehearsal`);
  `lineage` and each claim summarise it; each run's `REPORT.md` repeats its
  findings; the evidence graph gives it the role `design (not evidence)` and a
  `rehearses_on` edge. The graph digest of records without a rehearsal is
  unchanged.
- Resampling uses numpy's frozen `RandomState` stream, so a rehearsal derives
  identically under any numpy version.

**Studies and figures**

- Measurements are a function of the tests a study ran:
  `drr_stage.measure(report, analysis)` recomputes them from a report under any
  settings, and `run` uses the same code. It gives back every committed
  report's measurements exactly (tested).
- The categorical palette gains its validated fourth slot, so four-arm studies
  get figures; `figures.window_lengths` draws detection by window length.

**Records**

- V3D-EXP-0001 to 0003 bound no rehearsal and are unchanged. Rehearsed
  afterwards on the exploration their registrations bound, V3D-EXP-0002 fails
  in 1,000 of 1,000 resamples and V3D-EXP-0003 passes in 911: on those 20
  windows the 3 s, 6 s and breathing-derived windows never disagree, so every
  same-person contrast in both experiments is blind. Their verdicts and
  evidence levels stand; the README says what they are worth.
- New explorations of seen data (never evidence), run from a clean checkout at
  their specs' commit: a one-sample (0.25 s) rival window on the 190 windows
  V3D-EXP-0002 and 0003 judged (all 1,320 recorded tests reproduce with
  identical p-values; the rival detects 189 of 190 windows and meets every
  criterion 0003 applies to real recordings), and the young cohort cut into
  300, 120 and 60 s windows. The ceiling breaks between 5 and 2 minutes; the
  3 s, 6 s and derived windows stay within two points of each other at every
  length; the one-sample window gains on slow breathers and loses on normal
  ones. `docs/window-lengths.png` (`figures.window_lengths`) draws it.
- `specs/narrow-window-elderly.json`: the next experiment, drafted and
  rehearsed, not registered. It predicts that two-way effect in the unread
  elderly cohort, in 2-minute windows; its rehearsal is neither settled nor
  blind, and tells the one-sample window from the wide ones.

**Tests**

- Copies of the finished test repository get a private `origin`, so tests that
  push no longer collide.

## 0.3.0 — 2026-10-04

The evidence chain becomes checkable end to end, and failure modes that could
lose, burn or misstate evidence are closed.

**Safety (behaviour changes)**

- `register` no longer deletes `framing/<spec>/` when it holds another
  experiment's dossier. Retitling a registered spec (the documented way to start
  a new experiment) used to destroy the old experiment's committed framing; it
  is now refused, and the new experiment needs its own spec file.
- `register` refuses, before any literature search or data access: a spec that
  fails structural validation (`spec.py`); a definition R.A.I.N. would reject; a
  registered metric the study never produces (which used to end a holdout run as
  an error after spending the data); a holdout with no guard requiring zero early
  reads; a holdout that overlaps another registered holdout unless
  `data.holdout_shared_with` acknowledges the family; an analysis whose dry run
  on synthetic data fails.
- `run` refuses a holdout with `--allow-uncommitted`, a holdout on uncommitted
  or unpinned code, a framing dossier whose files, corpus, literature record or
  lineage no longer match the registration, and a registration changed in git
  history after its first commit. The anchor is now the *first* commit that
  holds the registration.
- Every failure after a run starts is filed by R.A.I.N. as an `error` run:
  crashes while writing artifacts, a submission R.A.I.N. rejects (kept as
  `submission.rejected.json`), a failure assembling the submission, and
  Ctrl-C (recorded, then re-raised). Previously these lost the run while the
  data stayed spent.
- Non-finite measurements are submitted as not measured (`null`), so criteria on
  them cannot hold, with an observation naming them; non-finite values in
  descriptive reports are written as `null`. NaN used to make the submission
  invalid after the data was read.
- A figure that fails to render no longer voids a measured run.
- Holdout reads are ordered against the anchor conservatively (git records whole
  seconds, so a read within the commit's second counts as early), and a holdout
  run waits for that second to pass. New pipeline measurement
  `holdout_bytes_read_before_anchor` closes the gap where data read between
  registration and anchoring looked unseen.
- The ledger is written atomically under a lock (concurrent runs could drop each
  other's reads), validated on load, and no longer logs a "first read" for bytes
  already read under other bounds. Explorations and replays only check it.
- Run, exploration and receipt names no longer collide within one second.
- DRR worker processes are spawned, not forked (fork from a multi-threaded
  process can deadlock; spawn is what the Windows runs used).

**Verification and lineage**

- `verify` re-derives the whole chain (`evidence.py`): artifacts and submissions
  re-hashed; each R.A.I.N. record compared field by field with its submission;
  framing files, Anna fingerprint and panel-corpus fingerprint against their
  bindings; the anchor commit holds the registration, is in history and
  predates the run; the registration unchanged across history; the ledger
  append-only across every committed version and since the snapshot each
  holdout registration bound; holdout bytes unread before registration and
  before the anchor; every dataset range in the ledger with identical content;
  every first read accounted for by a run; explorations only on seen bytes;
  recorded code resolved to a commit; `RESULTS.md` identical to R.A.I.N.'s
  render; summaries and reports stating the recorded outcome; unrecorded
  attempts surfaced. `--strict` fails when a check cannot run (CI).
- Each claim gets an evidence level derived from those checks: confirmatory
  (anchored and pushed before the run, holdout unread before the anchor),
  preregistered, registered or unverified.
- `lineage` prints the chain behind every claim; `lineage --json` exports the
  evidence graph (nodes with hashes, typed edges, a digest identifying the
  evidence state, shared-holdout families).
- `replay` re-executes a recorded run from its registration alone and writes a
  receipt comparing every registered measurement, series and study-report value.

**Interfaces**

- New commands: `replay`, `lineage`, `publish`; `--root`, `--version`; a
  `rain-pipeline` console script. Documented exit codes: 0 outcome recorded,
  1 broken evidence or failed replay, 2 refused, 3 error run.
- `RESULTS.md` names commands that exist in this repository (R.A.I.N.'s
  renderer named its own host's `rain_lab.py` and a missing `EXPERIMENTS.md`).
- Studies publish contracts (accepted settings, declared outputs, dry run).
- Runs record per-module source hashes, the pipeline's own git state, submodule
  pins, more package versions, and which registered metrics were evaluated
  versus descriptive.
- The 0.2 Python API (`explore/register/run/verify` with `registry_root=`,
  `data_root=`, ...) still works; new code passes a `Layout`.

**Packaging**

- One version source (`rain_pipeline.__version__`); the user agent no longer says 0.1.
- `constraints.txt` pins the environment the committed results were replayed in.
- CI: strict `verify` on full history, lint, the suite on Python 3.10–3.12, a clean
  wheel install, and a weekly replay of V3D-EXP-0001 against PhysioNet.

## 0.2.0 — 2026-10-04

- Explore / register / run protocol, data ledger, and the `lag_window` study
  (`9718470`). Produced V3D-EXP-0002 and V3D-EXP-0003, pre-registered in
  `4b4a030` and recorded in `8eb915b`.
- Architecture and protocol documents, CI (`28ad842`).
- Until `355ab7a`, `pyproject.toml` still declared 0.1.0 while the runtime
  declared 0.2.0; runs recorded the runtime version.

## 0.1.0 — 2026-10-04

- Anna → R.A.I.N. → DRR pipeline and V3D-EXP-0001 (`19de682`); its first attempt
  (`runs/20261004T145937Z`) crashed before submitting and is kept with its note.
- Anna, R.A.I.N. and DRR pinned as submodules at the commits that produced it (`36818a2`).
