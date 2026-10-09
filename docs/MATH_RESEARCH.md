# Mathematical research agenda: rain-pipeline

**State: proposed, not tested.** No mathematical paper, theorem or production algorithm has been imported into this application.

[OpenAI's `math`](https://github.com/openai/math) consists of research manuscripts and formal proof artifacts with varying verification status, not an API that makes another model or product intrinsically smarter. [Its README](https://github.com/openai/math/blob/main/README.md) warns that some unformalized results may have issues. The shared [R.A.I.N. Lab](https://github.com/topherchris420/lop-nur-twin) already stores a read-only, commit-pinned catalog; other projects should **reuse its provenance-aware research questions**, not fork the entire corpus.

Upstream inspected at commit [`fd4aeeb2ee4f`](https://github.com/openai/math/tree/fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb) on 9 October 2026. The local R.A.I.N. catalog may pin a different release, which is always declared in its scouting report.

## Question

**Can a preregistered effect survive a subject-level holdout and a falsifying negative control?**

Candidate lexical search: `statistical independent samples estimation bound`

From `topherchris420/lop-nur-twin`:

```sh
npm run rain:math:verify
npm run rain:math:portfolio -- --project rain-pipeline --json
```

Scouting ranks *possible* references and emits source revisions; it never says a theorem applies to this code, never compiles Lean, and never changes data or a decision. No matches is an acceptable outcome.

## Assumptions

1. Independence is defined at the person or session level, not silently at a segment level.
2. The designated holdout is unseen to the pipeline before publication of the registration.
3. Software replay verifies computations, not independent replication on new participants.

## Established starting point

`python -m rain_pipeline verify --strict` and `python -m rain_pipeline replay V3D-EXP-0002 --no-write`

## Proposed comparison

Register a new protocol with a genuinely independent subject-level holdout and a pair-breaking permutation control, then execute it only after the criteria and metric thresholds are publicly anchored.

**Required negative control:** Randomize pairings across people while preserving each time series' autocorrelation; the negative control should not show an established physiological coupling.

**Target artifact:** Registered spec, public commit, first-read ledger, independently tested subjects, controls, fresh result and byte-level replay receipt.

## What success would not imply

This is not permission to revise past results. The pinned historical R.A.I.N. submodule remains the version the original experiments ran. A mathematical theorem or new text cannot change the failed V3D-EXP-0002 verdict.

An experiment must be implemented and benchmarked before this status can change. Preserve unsuccessful outcomes; avoid claiming new performance until both the controlled comparison and its evidence record exist.

**Current status:** `NOT TESTED` for this mathematics extension.

[Read shared scouting protocol](https://github.com/topherchris420/lop-nur-twin/blob/main/docs/MATH_PORTFOLIO.md) · [Inspect OpenAI's manuscript map](https://github.com/openai/math/blob/fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb/CONTENTS.md)
