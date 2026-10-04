# Experimental Results

<!-- Generated from experiments/ by `python rain_lab.py experiment results`. Do not edit by hand. -->

What R.A.I.N. actually ran, and what happened. Each status is computed by host code
from recorded measurements against criteria registered *before* the run; no model
decides it. Failed and inconclusive results stay on the record.
How to add one: [EXPERIMENTS.md](EXPERIMENTS.md). Raw records: [`experiments/`](experiments/).

**1 experiments · 1 runs** — 1 passed · 0 failed

Evidence: 1 measured

| ID | Experiment | Result | Key measurement | Evidence | Runs |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0001](#v3d-exp-0001) | Does DRR recover respiration-to-heart-rate coupling (RSA) in resting young adults? | **PASSED** | coupling_detection_rate = 0.9 (needs ≥ 0.8) | measured | 1 |

## Negative and inconclusive results

None recorded yet.

## V3D-EXP-0001

### Does DRR recover respiration-to-heart-rate coupling (RSA) in resting young adults?

**Result: PASSED** — hypothesis supported · evidence: measured · runs: 1 (1 passed)

**Question:** Can DRR's surrogate-tested lead-lag analysis detect the well-established coupling from respiration to heart rate in real resting recordings, while not detecting it between different people?

**Hypothesis:** In at least 80% of 10-minute resting recordings from healthy young adults (PhysioNet Fantasia), DRR detects respiration -> heart-rate coupling (max-statistic adjusted p <= 0.05, lags 0.25-3 s), given that mismatched-subject pairs are detected in at most 25% and the synthetic controls behave as calibrated.

Measurements from V3D-EXP-0001-RUN-0001:

| Metric | Value | Criteria |
| --- | --- | --- |
| `records_analyzed` | 20 | G1: records_analyzed ≥ 16 (holds) |
| `coupling_detection_rate` | 0.9 | S1: coupling_detection_rate ≥ 0.8 (holds); F1: coupling_detection_rate < 0.5 (does not hold) |
| `mismatched_detection_rate` | 0.05 | G4: mismatched_detection_rate ≤ 0.25 (holds) |
| `detection_rate_gap` | 0.85 | — |
| `positive_control_detection_rate` | 1 | G2: positive_control_detection_rate ≥ 0.9 (holds) |
| `synthetic_null_false_positive_rate` | 0.05 | G3: synthetic_null_false_positive_rate ≤ 0.15 (holds) |
| `reverse_detection_rate` | 0.9 | — |
| `median_coupling_lag_s` | 0.5 s | — |
| `spectral_peak_agreement_rate` | 0.2 | — |
| `median_respiratory_frequency_hz` | 0.273438 Hz | — |
| `median_heart_rate_bpm` | 62.835 bpm | — |

**Evaluation:** All 1 success criteria held and no failure criterion triggered.

**Reproduction:** not yet reproduced.

| Run | Kind | Status | Commit | Seed | Finished |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0001-RUN-0001](experiments/V3D-EXP-0001/runs/RUN-0001/result.json) | external | passed | `862c4f75e6` | 20261004 | 2026-10-04 15:05:50 |

**Artifacts:** anna_record.json (hash only), anna_verification.json (hash only), panel_meeting.md (hash only), panel_summary.json (hash only), drr_report.json (hash only)

**Limitations:**

- Lagged correlation ignores sign and lag 0, and respiration and heart rate share one rhythm, so the reverse direction may score as high: this tests coupling, not direction.
- Fantasia subjects are healthy young adults in supine rest watching the film Fantasia; nothing here generalizes to other ages, conditions or postures.
- R peaks come from a simple band-pass detector; records below the QC threshold are excluded, not repaired.
- Respiratory sinus arrhythmia is established physiology; this experiment tests whether DRR recovers it, not whether it exists.
- Literature retrieval uses Anna's deterministic hashing embeddings (lexical, not semantic) over arXiv metadata and abstracts only.

**Reproduce:** `python rain_lab.py experiment reproduce V3D-EXP-0001`
