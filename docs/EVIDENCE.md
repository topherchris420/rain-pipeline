# Evidence: how claims are checked, graded and re-executed

A claim in this repository is the verdict R.A.I.N. assigned to one run. This document says how `verify` checks the chain beneath each claim, how a claim's evidence level follows from those checks, what a replay proves, and the formats of the machine-readable records.

## What verify checks

`python -m rain_pipeline verify` reads the repository and its git history, writes nothing, and reports one line per link. Each link gets one of four statuses:

- **ok**: the link holds.
- **fail**: it is broken; a hash, a binding, a time order or a record disagrees. The command exits 1.
- **warn**: the record is honest but weaker than the protocol's standard.
- **skip**: the link cannot be checked here (no git work tree, or a shallow clone). `--strict` turns skips into failures; CI uses it.

| check | subject | re-derives | fails when |
|---|---|---|---|
| `rain.verify` | registry | R.A.I.N.'s own verification: every status, verdict and statistic recomputed from stored measurements and series | any record disagrees with its recomputation |
| `registration.history` | experiment | every committed version of `experiment.json` | it changed after its first commit, or is edited in the working tree (*warn*: never committed) |
| `registration.spec` | experiment | the spec that framed it, compared with the registration | the spec was edited after registration (*warn*: the spec is gone or retitled) |
| `framing.manifest` | experiment | `framing.json` names this registration at this definition hash | the registration changed since framing |
| `framing.files` | experiment | SHA-256 and size of each framing file | any file changed or is missing |
| `framing.anna` | experiment | Anna's fingerprint of the literature record; the bound record hash | the record no longer seals, or is not the one bound |
| `framing.corpus` | experiment | the panel-corpus fingerprint from the files on disk (R.A.I.N.'s algorithm) | it differs from the citation audit or the binding |
| `lineage.parent`, `lineage.exploration` | experiment | the bound parent result and exploration report | missing, changed, or not an exploration |
| `holdout.before_registration` | experiment | bytes of the holdout first read before the registration | any |
| `holdout.ledger_snapshot` | experiment | the ledger version bound at registration, found in git history | the current ledger does not extend it, or it shows holdout reads (*warn*: never committed) |
| `holdout.before_anchor` | experiment | bytes first read before the first commit holding the registration (rounded up to the next whole second) | any |
| `run.submission` | run | the `submission.json` whose canonical SHA-256 R.A.I.N. recorded; the record compared with it field by field | none matches, or the record's measurements, series, inputs, seed, times or artifacts differ from it |
| `run.artifacts` | run | SHA-256 and size of every artifact the record names | any changed or missing |
| `run.summary`, `run.report` | run | the human-facing `summary.json` and `REPORT.md` heading | they state another run, status, verdict or measurements |
| `run.timing` | run | registration time against run start | the run started before its registration existed |
| `run.data` | run | every dataset range the run read, against the ledger | content differs, or bytes were never logged |
| `run.anchor` | run | the recorded anchor commit: present, holds this exact registration, in HEAD's history, committed before the run started | any of those (*warn*: no anchor, as for V3D-EXP-0001) |
| `run.published` | run | whether the anchor commit was on a remote branch when the run started, as the run recorded it | *warn* only: an unpushed anchor's time rests on one machine's clock |
| `run.code` | run | the recorded pipeline source digest, matched against every commit that changed the package | *warn* only: the code was never committed |
| `ledger.schema`, `ledger.history` | ledger | entry shape; every committed version extends the previous one, and the working tree extends HEAD | an entry is malformed, removed or changed |
| `ledger.accounted` | ledger | each first read belongs to a recorded run of the experiment that made it | an exploration is a first reader (*warn*: a read no run accounts for, e.g. an interrupted run) |
| `exploration.label`, `exploration.data` | exploration | the exploratory label; every byte seen before the exploration | unlabelled, or it read unseen bytes |
| `runs.unrecorded`, `framing.unregistered` | runs, framing | directories no record refers to | *warn* only: an attempt with no R.A.I.N. record stays visible |
| `results.page` | `RESULTS.md` | the page R.A.I.N. renders from the registry | it was edited by hand or is stale |
| `receipt.binding` | receipt | the replayed run's record hash; the outcome implied by the receipt's own comparison | the run changed since the replay, or the stated outcome overstates the comparison |

A check that crashes on a malformed record is reported as a failure, never allowed to stop verification.

## Evidence levels

Each run gets a level that follows mechanically from the checks on its experiment and on itself:

| level | meaning |
|---|---|
| **confirmatory** | registered; anchored in git and pushed before the run; on a declared holdout no byte of which was read before the anchor; every link verified |
| **preregistered** | registered and anchored in git before the run; every link verified (no holdout, or the anchor was not pushed before the run) |
| **registered** | criteria recorded by R.A.I.N. before the run, but not anchored in git before it |
| **unverified** | a link in its chain failed verification; treat the verdict as unsupported |

The level grades the *chain*, not the hypothesis. A confirmatory FAILED is strong evidence against a hypothesis; a registered PASSED is weaker evidence for one. Explorations have no level: they are observations, never evidence.

`lineage` also states, for each claim:

- **New data versus new subjects.** It lists which of the claim's records earlier experiments already analysed.
- **Shared holdouts.** Experiments judged on overlapping held-out bytes form a family, each evaluated on its own criteria with no correction across it. Since 0.3.0, registering into such a family requires `data.holdout_shared_with`.
- **Code identity.** It names the commit whose source matches the recorded digest.
- **Replays.** It lists each receipt's outcome.

## Replay

`python -m rain_pipeline replay EXP-ID [--run RUN-NNNN]` re-executes a recorded run from its registration alone. It reads the exact byte ranges the registration names and refuses if any byte was never read by a run. Every byte must hash as the ledger says. It then runs the registered study with the registered seed, recomputes the pipeline's holdout measurements from the ledger, and has R.A.I.N.'s evaluator judge the replayed measurements. It never writes to the registry or the ledger.

The outcome follows from the comparison alone, graded by the same line the protocol draws everywhere (registered measurements are evidence; series and the study report are description). No numeric tolerance is involved; the receipt records every difference and the largest.

| outcome | meaning | exit |
|---|---|---|
| `reproduced` | every registered measurement, series value and study-report value identical; same verdict | 0 |
| `measurements-reproduced` | every registered measurement identical, same verdict; some descriptive value differs | 0 |
| `verdict-reproduced` | same verdict, but some registered measurement differs | 1 |
| `verdict-differs` | R.A.I.N. reaches another status on the replayed measurements | 1 |
| `error` | the replay could not complete (the receipt records where and why, e.g. substituted data) | 3 |

Receipts are written to `replays/<EXP-ID>/RUN-NNNN-<UTC time>.json`:

```json
{
  "schema": "rain-pipeline-replay-receipt/v1",
  "replayed_at": "…",
  "replayed": {"experiment_id", "run_id", "result_sha256", "definition_sha256", "submission_sha256"},
  "environment": {"python", "implementation", "platform", "packages": {"numpy": "…", …}},
  "code": {"pipeline": {"version", "source_sha256", "files", "git"}, "vendored": {…}},
  "recorded_code": {…the run's own record of its code…},
  "data": [{"record", "url", "byte_range", "sha256", "matches_ledger", "matches_run"}],
  "comparison": {
    "measurements": {"<name>": {"recorded", "replayed", "identical", "difference"}},
    "series": {"<name>": {"recorded_n", "replayed_n", "identical", "max_abs_difference"}},
    "report": {"identical", "differing_values", "first_differences", "max_abs_difference",
               "recorded_sha256", "replayed_sha256"},
    "status": {"recorded", "replayed"}, "verdict": {"recorded", "replayed"},
    "data_identical": true, "error": null
  },
  "outcome": "reproduced"
}
```

`verify` checks every receipt: it must refer to the run record as it still is, and its stated outcome must be the one its comparison implies.

## The evidence graph

`python -m rain_pipeline lineage --json` prints:

```json
{
  "schema": "rain-pipeline-evidence-graph/v1",
  "digest": "<canonical SHA-256 of nodes and edges>",
  "families": [{"kind": "shared-holdout", "experiments": ["V3D-EXP-0002", "V3D-EXP-0003"], "note": "…"}],
  "nodes": [{"id": "run:V3D-EXP-0002-RUN-0001", "kind": "run", "role": "measurement", "sha256": "…"}, …],
  "edges": [{"from": "run:…", "relation": "tests", "to": "registration:…"}, …],
  "claims": [{"run_id", "status", "verdict", "assigned_by", "evidence_level", "broken_links", "weaker_links",
              "data": {"records", "records_analysed_by_earlier_experiments", "held_out"},
              "shares_holdout_with", "code": {"version", "source_sha256", "commit"}, "replays": […]}, …]
}
```

Node roles make the epistemic status of every record explicit: `intent` (spec), `criteria` (registration), `temporal anchor` (commit), `context (not evidence)` (literature, panel), `observation (not evidence)` (exploration), `input` (data range), `measurement` (run), `evaluation` (verdict), `artifact`, `implementation` (code), `reproduction` (receipt).

The graph is derived from committed files only. Its digest is stable for a given set of records and changes when any of them, or any bound file, changes. `claims` comes from the live checks and is not part of the digest. A consumer can recompute everything from a clone; nothing in the graph has to be taken on trust.
