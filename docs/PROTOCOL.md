# Experimental Protocol

This document is the operating contract for extending `rain-pipeline` without weakening its evidence model.

## Lifecycle

### 1. Explore

Use `explore` only for questions about data already recorded in `data/ledger.json`.

Exploration may discover:
- useful window lengths
- signal-quality problems
- plausible controls
- candidate statistics
- implementation failures

Exploration must not be described as confirmation. Its outputs are labelled explicitly as exploratory.

### 2. Register

A registration should state, before confirmation data are read:
- the question
- the hypothesis
- the dataset and exact segments
- the analysis parameters
- the seed
- guards
- success criteria
- failure criteria
- known limitations
- optional lineage to a prior result or exploration

The registration binds its literature and lineage artifacts by hash.

### 3. Anchor

Commit and push the registration before running a holdout experiment.

Do not use `--allow-uncommitted` for evidence intended to support a public claim. That option exists for development and explicitly weakens the temporal guarantee.

### 4. Run

The runner:
1. checks the registration
2. plans exact byte ranges
3. records reads in the ledger
4. applies pre-registered QC
5. computes the declared analysis
6. emits registered measurements
7. records controls and artifacts
8. submits the result without assigning its own verdict

### 5. Evaluate

R.A.I.N. evaluates the submission against the criteria that existed in the registration.

A result can support, contradict, remain unresolved, or error. These states should not be collapsed into a binary success/failure story.

### 6. Verify

`verify` should be treated as a reproducibility audit:
- recompute stored results where supported
- validate registration hashes
- validate artifact hashes
- validate literature bindings
- validate lineage bindings
- validate holdout timing
- surface warnings instead of hiding uncertainty

## Design rules for contributors

### Do
- preserve deterministic seeds
- keep provenance close to outputs
- add tests for every new evidence invariant
- make failure modes explicit
- prefer small, composable stages
- keep external repositories pinned
- preserve raw evidence and negative results
- make new experiments additive rather than mutating old registrations

### Do not
- add a status field to raw submissions and let the runner decide the verdict
- read holdout data during exploration
- mutate a registration after data access
- silently change an analysis parameter for an existing experiment
- delete failed or inconclusive runs
- treat a higher correlation, lower p-value, or prettier figure as a reason to change criteria
- hide excluded windows or mismatched controls

## Adding a new analysis

A new analysis should have:
1. a small adapter in `rain_pipeline/`
2. a declarative representation in `specs/`
3. unit tests for edge cases
4. at least one positive control and one null/control where scientifically appropriate
5. an explicit list of measurements that may become evidence
6. a report section separating evidence from description

If the analysis computes additional diagnostics, those diagnostics may remain in the report, but they do not become evidence unless they were registered.

## Reproducibility hierarchy

From strongest to weakest:
1. registered + committed + pushed + holdout-unseen + verified
2. registered + committed + holdout-unseen + verified locally
3. registered + committed + run, not yet verified
4. registered but uncommitted
5. exploratory
6. informal/manual analysis outside the pipeline

The project should make level 1 the normal destination for public claims.
