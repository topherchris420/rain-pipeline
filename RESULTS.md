# Experimental Results

<!-- Generated from experiments/ by `python -m rain_pipeline publish` (R.A.I.N.'s results renderer). Do not edit by hand. -->

What R.A.I.N. actually ran, and what happened. Each status is computed by host code
from recorded measurements against criteria registered *before* the run; no model
decides it. Failed and inconclusive results stay on the record.
How to add one: [docs/PROTOCOL.md](docs/PROTOCOL.md). Raw records: [`experiments/`](experiments/).

**3 experiments · 3 runs** — 2 passed · 1 failed

Evidence: 3 measured

| ID | Experiment | Result | Key measurement | Evidence | Runs |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0001](#v3d-exp-0001) | Does DRR recover respiration-to-heart-rate coupling (RSA) in resting young adults? | **PASSED** | coupling_detection_rate = 0.9 (needs ≥ 0.8) | measured | 1 |
| [V3D-EXP-0002](#v3d-exp-0002) | Does a 6 s lag window recover respiration-to-heart-rate coupling in slow breathers? (held-out Fantasia windows) | **FAILED** | slow_detection_rate_long = 1 (needs ≥ 0.8) | measured | 1 |
| [V3D-EXP-0003](#v3d-exp-0003) | Can DRR derive its lag window from the breathing resonance instead of a hand-picked length? (held-out Fantasia windows) | **PASSED** | slow_resonant_vs_long = 0 (needs ≥ -0.05) | measured | 1 |

## Negative and inconclusive results

- **V3D-EXP-0002 — FAILED**: Does a 6 s lag window recover respiration-to-heart-rate coupling in slow breathers? (held-out Fantasia windows). Failure criterion met: F1: slow_gain_long_vs_short ≤ 0 (observed 0).

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

**Reproduce:** `python -m rain_pipeline replay V3D-EXP-0001`

## V3D-EXP-0002

### Does a 6 s lag window recover respiration-to-heart-rate coupling in slow breathers? (held-out Fantasia windows)

**Result: FAILED** — hypothesis not supported · evidence: measured · runs: 1 (1 failed)

**Question:** On recordings never analysed before, does widening DRR's lag window from 3 s to 6 s raise detection of respiration -> heart-rate coupling when breathing is slow, without making the test fire on mismatched people?

**Hypothesis:** In held-out 10-minute windows from the Fantasia young cohort (seconds 660-6660 of each record), widening the lag window from 3 s to 6 s raises the subject-balanced detection rate of respiration -> heart-rate coupling in slow-breathing windows (dominant breathing frequency from 0.0833 Hz up to, but not including, 0.1667 Hz) by at least 0.10, to at least 0.80, lowers it by no more than 0.05 in normal-breathing windows, and keeps detections between mismatched people at or below 0.10.

Measurements from V3D-EXP-0002-RUN-0001:

| Metric | Value | Criteria |
| --- | --- | --- |
| `holdout_bytes_read_before_registration` | 0 bytes | G1: holdout_bytes_read_before_registration ≤ 0 (holds) |
| `windows_analyzed` | 190 | G2: windows_analyzed ≥ 160 (holds) |
| `slow_windows` | 33 | G4: slow_windows ≥ 20 (holds) |
| `slow_subjects` | 13 | G3: slow_subjects ≥ 4 (holds) |
| `normal_windows` | 114 | — |
| `normal_subjects` | 19 | — |
| `slow_detection_rate_short` | 1 | — |
| `slow_detection_rate_long` | 1 | S1: slow_detection_rate_long ≥ 0.8 (holds) |
| `slow_gain_long_vs_short` | 0 | S2: slow_gain_long_vs_short ≥ 0.1 (does not hold); F1: slow_gain_long_vs_short ≤ 0 (holds) |
| `normal_detection_rate_short` | 1 | — |
| `normal_detection_rate_long` | 1 | — |
| `normal_change_long_vs_short` | 0 | S3: normal_change_long_vs_short ≥ -0.05 (holds); F2: normal_change_long_vs_short < -0.15 (does not hold) |
| `mismatched_detection_rate_short` | 0.0157895 | — |
| `mismatched_detection_rate_long` | 0.0157895 | S4: mismatched_detection_rate_long ≤ 0.1 (holds); F3: mismatched_detection_rate_long > 0.15 (does not hold) |
| `mismatched_slow_detection_rate_short` | 0 | — |
| `mismatched_slow_detection_rate_long` | 0 | — |
| `window_detection_rate_short` | 1 | — |
| `window_detection_rate_long` | 1 | — |
| `slow_median_lag_s_short` | 0.25 s | — |
| `slow_median_lag_s_long` | 0.25 s | — |
| `synthetic_long_lag_detection_rate_short` | 0 | — |
| `synthetic_long_lag_detection_rate_long` | 1 | G5: synthetic_long_lag_detection_rate_long ≥ 0.9 (holds) |
| `synthetic_positive_detection_rate_long` | 1 | — |
| `synthetic_null_false_positive_rate_long` | 0 | G6: synthetic_null_false_positive_rate_long ≤ 0.15 (holds) |

**Evaluation:** Failure criterion met: F1: slow_gain_long_vs_short ≤ 0 (observed 0).

**Reproduction:** not yet reproduced.

| Run | Kind | Status | Commit | Seed | Finished |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0002-RUN-0001](experiments/V3D-EXP-0002/runs/RUN-0001/result.json) | external | failed | `862c4f75e6` | 20261005 | 2026-10-04 18:10:57 |

**Artifacts:** drr_report.json (hash only), figure.png (hash only), anna_record.json (hash only), anna_verification.json (hash only), panel_meeting.md (hash only), panel_summary.json (hash only)

**Limitations:**

- The held-out windows come from the same 20 people as V3D-EXP-0001: new data, not new people. Slow breathing is concentrated in a few of them, so rates weight each person equally and the guards require at least four slow breathers.
- Detection means max-statistic adjusted p <= 0.05 for respiration -> heart rate. Lagged correlation ignores sign and lag 0, so this tests coupling, not direction.
- Strata come from the dominant Welch peak of respiration (64 s segments, 0.0156 Hz resolution). Windows slower than 0.0833 Hz fall in neither stratum.
- Mismatched pairs share the time into the recording, and every subject watched the same film. A film-locked common response would raise mismatched detections and count against the hypothesis.
- Windows from one person are not independent, so mismatched and window-level shares are less certain than their counts suggest.
- R peaks come from a simple band-pass detector; windows below the QC threshold are excluded, not repaired.
- The holdout guarantee rests on this tool's data ledger: it shows no byte of these ranges was read through the pipeline before registration, and cannot rule out reads made outside it.
- A sibling experiment (specs/resonance-derived-window.json) was registered alongside this one and is judged on the same held-out windows. Each is evaluated on its own criteria; there is no correction across the two.
- Literature retrieval uses Anna's deterministic hashing embeddings (lexical, not semantic) over arXiv metadata and abstracts only.

**Reproduce:** `python -m rain_pipeline replay V3D-EXP-0002`

## V3D-EXP-0003

### Can DRR derive its lag window from the breathing resonance instead of a hand-picked length? (held-out Fantasia windows)

**Result: PASSED** — hypothesis supported · evidence: measured · runs: 1 (1 passed)

**Question:** Does a lag window set per recording to half the breathing period, as measured by DRR's own resonance detector, detect respiration -> heart-rate coupling as often as the better hand-picked window in each breathing range, without firing on mismatched people?

**Hypothesis:** On held-out 10-minute windows from the Fantasia young cohort (seconds 660-6660 of each record), a lag window derived per window from DRR's resonance detector (half the dominant breathing period plus one sample, clamped to 1-8 s) detects respiration -> heart-rate coupling at a subject-balanced rate within 0.05 of the fixed 6 s window in slow-breathing windows and within 0.05 of the fixed 3 s window in normal-breathing windows, while detections between mismatched people stay at or below 0.10.

Measurements from V3D-EXP-0003-RUN-0001:

| Metric | Value | Criteria |
| --- | --- | --- |
| `holdout_bytes_read_before_registration` | 0 bytes | G1: holdout_bytes_read_before_registration ≤ 0 (holds) |
| `windows_analyzed` | 190 | G2: windows_analyzed ≥ 160 (holds) |
| `slow_windows` | 33 | G4: slow_windows ≥ 20 (holds) |
| `slow_subjects` | 13 | G3: slow_subjects ≥ 4 (holds) |
| `normal_windows` | 114 | — |
| `normal_subjects` | 19 | — |
| `slow_detection_rate_resonant` | 1 | — |
| `slow_detection_rate_long` | 1 | — |
| `slow_detection_rate_short` | 1 | — |
| `slow_resonant_vs_long` | 0 | S1: slow_resonant_vs_long ≥ -0.05 (holds); F1: slow_resonant_vs_long < -0.15 (does not hold) |
| `normal_detection_rate_resonant` | 1 | — |
| `normal_detection_rate_short` | 1 | — |
| `normal_detection_rate_long` | 1 | — |
| `normal_resonant_vs_short` | 0 | S2: normal_resonant_vs_short ≥ -0.05 (holds); F2: normal_resonant_vs_short < -0.15 (does not hold) |
| `mismatched_detection_rate_resonant` | 0.0157895 | S3: mismatched_detection_rate_resonant ≤ 0.1 (holds); F3: mismatched_detection_rate_resonant > 0.15 (does not hold) |
| `mismatched_detection_rate_short` | 0.0157895 | — |
| `mismatched_detection_rate_long` | 0.0157895 | — |
| `mismatched_long_vs_resonant` | 0 | — |
| `mismatched_slow_detection_rate_resonant` | 0 | — |
| `window_detection_rate_resonant` | 1 | — |
| `slow_median_lag_s_resonant` | 0.25 s | — |
| `normal_median_lag_s_resonant` | 0.5 s | — |
| `synthetic_positive_detection_rate_resonant` | 1 | G5: synthetic_positive_detection_rate_resonant ≥ 0.9 (holds) |
| `synthetic_null_false_positive_rate_resonant` | 0.05 | G6: synthetic_null_false_positive_rate_resonant ≤ 0.15 (holds) |

**Evaluation:** All 3 success criteria held and no failure criterion triggered.

**Reproduction:** not yet reproduced.

| Run | Kind | Status | Commit | Seed | Finished |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0003-RUN-0001](experiments/V3D-EXP-0003/runs/RUN-0001/result.json) | external | passed | `862c4f75e6` | 20261005 | 2026-10-04 18:33:08 |

**Artifacts:** drr_report.json (hash only), figure.png (hash only), anna_record.json (hash only), anna_verification.json (hash only), panel_meeting.md (hash only), panel_summary.json (hash only)

**Limitations:**

- The claim is relative. If neither fixed window detects slow breathers well, matching them does not mean slow breathers are detected.
- The derived window depends on the breathing-frequency estimate (dominant Welch peak, 0.0156 Hz resolution). A wrong peak gives a wrong window; the 1-8 s clamp bounds the damage.
- The synthetic controls have no rhythm, so their derived windows are arbitrary within the clamp. They check calibration, not the rule.
- The held-out windows come from the same 20 people as V3D-EXP-0001: new data, not new people. Rates weight each person equally.
- Detection means max-statistic adjusted p <= 0.05 for respiration -> heart rate. Lagged correlation ignores sign and lag 0, so this tests coupling, not direction.
- Mismatched pairs share the time into the recording, and every subject watched the same film. A film-locked common response would raise mismatched detections and count against the hypothesis.
- The holdout guarantee rests on this tool's data ledger: it shows no byte of these ranges was read through the pipeline before registration, and cannot rule out reads made outside it.
- A sibling experiment (specs/slow-breathers-6s-window.json) was registered alongside this one and is judged on the same held-out windows. Each is evaluated on its own criteria; there is no correction across the two.
- Literature retrieval uses Anna's deterministic hashing embeddings (lexical, not semantic) over arXiv metadata and abstracts only.

**Reproduce:** `python -m rain_pipeline replay V3D-EXP-0003`
