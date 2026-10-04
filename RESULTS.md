# Experimental Results

<!-- Generated from experiments/ by `python rain_lab.py experiment results`. Do not edit by hand. -->

What R.A.I.N. actually ran, and what happened. Each status is computed by host code
from recorded measurements against criteria registered *before* the run; no model
decides it. Failed and inconclusive results stay on the record.
How to add one: [EXPERIMENTS.md](EXPERIMENTS.md). Raw records: [`experiments/`](experiments/).

**3 experiments · 1 runs** — 1 passed · 0 failed · 2 planned

Evidence: 1 measured · 2 proposed

| ID | Experiment | Result | Key measurement | Evidence | Runs |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0001](#v3d-exp-0001) | Does DRR recover respiration-to-heart-rate coupling (RSA) in resting young adults? | **PASSED** | coupling_detection_rate = 0.9 (needs ≥ 0.8) | measured | 1 |
| [V3D-EXP-0002](#v3d-exp-0002) | Does a 6 s lag window recover respiration-to-heart-rate coupling in slow breathers? (held-out Fantasia windows) | **PLANNED** | slow_detection_rate_long: — (needs ≥ 0.8) | proposed | 0 |
| [V3D-EXP-0003](#v3d-exp-0003) | Can DRR derive its lag window from the breathing resonance instead of a hand-picked length? (held-out Fantasia windows) | **PLANNED** | slow_resonant_vs_long: — (needs ≥ -0.05) | proposed | 0 |

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

## V3D-EXP-0002

### Does a 6 s lag window recover respiration-to-heart-rate coupling in slow breathers? (held-out Fantasia windows)

**Result: PLANNED** — no runs yet · evidence: proposed · runs: 0 (none completed)

**Question:** On recordings never analysed before, does widening DRR's lag window from 3 s to 6 s raise detection of respiration -> heart-rate coupling when breathing is slow, without making the test fire on mismatched people?

**Hypothesis:** In held-out 10-minute windows from the Fantasia young cohort (seconds 660-6660 of each record), widening the lag window from 3 s to 6 s raises the subject-balanced detection rate of respiration -> heart-rate coupling in slow-breathing windows (dominant breathing frequency from 0.0833 Hz up to, but not including, 0.1667 Hz) by at least 0.10, to at least 0.80, lowers it by no more than 0.05 in normal-breathing windows, and keeps detections between mismatched people at or below 0.10.

**Pre-registered criteria** (nothing measured yet):

- Guard G1: holdout_bytes_read_before_registration ≤ 0
- Guard G2: windows_analyzed ≥ 160
- Guard G3: slow_subjects ≥ 4
- Guard G4: slow_windows ≥ 20
- Guard G5: synthetic_long_lag_detection_rate_long ≥ 0.9
- Guard G6: synthetic_null_false_positive_rate_long ≤ 0.15
- Success S1: slow_detection_rate_long ≥ 0.8
- Success S2: slow_gain_long_vs_short ≥ 0.1
- Success S3: normal_change_long_vs_short ≥ -0.05
- Success S4: mismatched_detection_rate_long ≤ 0.1
- Failure F1: slow_gain_long_vs_short ≤ 0
- Failure F2: normal_change_long_vs_short < -0.15
- Failure F3: mismatched_detection_rate_long > 0.15

**Next step:** run it — `topherchris420/dynamic-resonance-rooting` via `experiment record`.

## V3D-EXP-0003

### Can DRR derive its lag window from the breathing resonance instead of a hand-picked length? (held-out Fantasia windows)

**Result: PLANNED** — no runs yet · evidence: proposed · runs: 0 (none completed)

**Question:** Does a lag window set per recording to half the breathing period, as measured by DRR's own resonance detector, detect respiration -> heart-rate coupling as often as the better hand-picked window in each breathing range, without firing on mismatched people?

**Hypothesis:** On held-out 10-minute windows from the Fantasia young cohort (seconds 660-6660 of each record), a lag window derived per window from DRR's resonance detector (half the dominant breathing period plus one sample, clamped to 1-8 s) detects respiration -> heart-rate coupling at a subject-balanced rate within 0.05 of the fixed 6 s window in slow-breathing windows and within 0.05 of the fixed 3 s window in normal-breathing windows, while detections between mismatched people stay at or below 0.10.

**Pre-registered criteria** (nothing measured yet):

- Guard G1: holdout_bytes_read_before_registration ≤ 0
- Guard G2: windows_analyzed ≥ 160
- Guard G3: slow_subjects ≥ 4
- Guard G4: slow_windows ≥ 20
- Guard G5: synthetic_positive_detection_rate_resonant ≥ 0.9
- Guard G6: synthetic_null_false_positive_rate_resonant ≤ 0.15
- Success S1: slow_resonant_vs_long ≥ -0.05
- Success S2: normal_resonant_vs_short ≥ -0.05
- Success S3: mismatched_detection_rate_resonant ≤ 0.1
- Failure F1: slow_resonant_vs_long < -0.15
- Failure F2: normal_resonant_vs_short < -0.15
- Failure F3: mismatched_detection_rate_resonant > 0.15

**Next step:** run it — `topherchris420/dynamic-resonance-rooting` via `experiment record`.
