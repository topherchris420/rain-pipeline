# Architecture

`rain-pipeline` is an evidence pipeline, not a generic analysis script. Its defining property is that the path from question to verdict is explicit, inspectable, and resistant to accidental leakage between exploration and confirmation.

## System boundary

```
question
   │
   ├── explore ──► seen bytes only ──► exploratory report
   │
   ▼
register
   │
   ├── Anna: literature record
   ├── R.A.I.N.: panel/framing
   ├── experiment contract: hypothesis + metrics + guards + failure rules
   └── SHA-256 bindings: literature + lineage + exploration + holdout proof
   │
   ▼
git commit / push
   │
   │   criteria now have a public timestamp
   ▼
run
   │
   ├── byte-range acquisition + ledger
   ├── physiological/QC transformation
   ├── DRR analysis + controls
   └── submission with measurements only
   │
   ▼
R.A.I.N. evaluation
   │
   ├── supported
   ├── contradicted
   ├── unresolved
   └── error
   │
   ▼
verify
   └── re-derive + re-check provenance + holdout invariants
```

## Core invariants

1. **Exploration is not evidence.** Exploration can only consume bytes already present in the ledger.
2. **Holdouts are temporal, not merely nominal.** Registration records whether declared holdout bytes were seen before the registration existed.
3. **Registrations are write-once.** A changed hypothesis, metric, parameter, or lineage cannot silently mutate an existing experiment.
4. **The registration precedes confirmation.** Normal runs refuse an uncommitted registration. The commit is the auditable timestamp.
5. **The runner does not decide the result.** The study produces measurements; R.A.I.N. evaluates registered criteria.
6. **Controls travel with the claim.** Synthetic positives, synthetic nulls, mismatched subjects, and QC exclusions remain explicit artifacts.
7. **Provenance is part of the result.** Upstream repository commits, pipeline source digest, environment information, downloaded byte hashes, and artifact hashes are recorded.
8. **Negative results remain first-class.** A failed hypothesis is evidence about the hypothesis, not a broken pipeline.

## Trust boundaries

The pipeline distinguishes three kinds of authority:

- **Data authority:** the external source and the bytes actually consumed.
- **Analytic authority:** Anna, DRR, and the local orchestration code that transform those bytes.
- **Epistemic authority:** R.A.I.N.'s registered criteria and evaluation layer.

No stage is allowed to quietly inherit authority from another. Literature can inform a registration, but cannot rewrite its success criteria after data access. An exploratory pattern can motivate a new experiment, but cannot become evidence for the original claim.

## Artifact graph

```
spec
 ├── literature record ──┐
 ├── panel framing ──────┤
 ├── lineage ────────────┤
 ├── exploration ────────┤
 └── data ranges ────────┤
                          ▼
                   registration
                          │
                    git anchor
                          │
                          ▼
                     run result
                    ┌─────┴─────┐
                    ▼           ▼
                submission    artifacts
                    │
                    ▼
               R.A.I.N. verdict
```

The useful unit is therefore not a notebook or a model output. It is a **replayable claim with lineage**.

## Why this architecture matters

The interesting innovation is not that the pipeline can calculate a correlation. It is that the pipeline makes it difficult to confuse:

**something we noticed → something we registered → something we measured → something the criteria support.**

That distinction is the project's epistemic firewall.
