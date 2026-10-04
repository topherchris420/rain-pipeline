# V3D-EXP-0003-RUN-0001: PASSED

**Can DRR derive its lag window from the breathing resonance instead of a hand-picked length? (held-out Fantasia windows)**

- Question: Can DRR set its lag window from the breathing rhythm itself, half the respiratory period, instead of a hand-picked number of seconds?
- Hypothesis: On held-out 10-minute windows from the Fantasia young cohort (seconds 660-6660 of each record), a lag window derived per window from DRR's resonance detector (half the dominant breathing period plus one sample, clamped to 1-8 s) detects respiration -> heart-rate coupling at a subject-balanced rate within 0.05 of the fixed 6 s window in slow-breathing windows and within 0.05 of the fixed 3 s window in normal-breathing windows, while detections between mismatched people stay at or below 0.10.
- Verdict (assigned by R.A.I.N. `rain-criteria/v1`): supported
- All 3 success criteria held and no failure criterion triggered.
- R.A.I.N. re-verification: OK (1 run(s) re-derived from stored data)

## Criteria

| Id | Metric | Needs | Observed | Holds |
|---|---|---|---|---|
| G1 | `holdout_bytes_read_before_registration` | <= 0 | 0 | True |
| G2 | `windows_analyzed` | >= 160 | 190 | True |
| G3 | `slow_subjects` | >= 4 | 13 | True |
| G4 | `slow_windows` | >= 20 | 33 | True |
| G5 | `synthetic_positive_detection_rate_resonant` | >= 0.9 | 1 | True |
| G6 | `synthetic_null_false_positive_rate_resonant` | <= 0.15 | 0.05 | True |
| S1 | `slow_resonant_vs_long` | >= -0.05 | 0 | True |
| S2 | `normal_resonant_vs_short` | >= -0.05 | 0 | True |
| S3 | `mismatched_detection_rate_resonant` | <= 0.1 | 0.01579 | True |
| F1 | `slow_resonant_vs_long` | < -0.15 | 0 | False |
| F2 | `normal_resonant_vs_short` | < -0.15 | 0 | False |
| F3 | `mismatched_detection_rate_resonant` | > 0.15 | 0.01579 | False |

![Detection by breathing frequency and lag window](figure.png)

## Registration

- Registered: 2026-10-04T17:41:36.439Z
- Git commit: `4b4a0306b9ccb43ec6c32235190680684564326a` (2026-10-04T13:41:53-04:00); pushed to origin/held-out-lag-window-experiments, origin/main
- Holdout: 0 bytes of this data had been read before registration
- Follows: V3D-EXP-0001/RUN-0001. RUN-0001 used one hand-picked 3 s lag window for every person. It missed two slow breathers and detected a third only at the edge of that window.
- Exploration on seen data (not evidence): `explorations/20261004T173027Z-explore-lag-window/report.json`

## Literature (Anna)

Record `04b3db7e0e8728fcfaefe3ba37274d9e3c38dc3efa56bd9dba13eec365dc8607`

1. [Synchronization-dissipation dynamics in the cardiorespiratory system](http://arxiv.org/abs/2603.23259v1)
2. [Effect of stress on cardiorespiratory synchronization of Ironmen athletes](http://arxiv.org/abs/2102.01883v1)
3. [Cardiorespiratory coupling improves cardiac pumping efficiency in heart failure](http://arxiv.org/abs/2507.00597v1)
4. [Inference of a nonlinear stochastic model of the cardiorespiratory interaction](http://arxiv.org/abs/physics/0503040v1)
5. [Contact Sensors to Remote Cameras: Quantifying Cardiorespiratory Coupling in High-Altitude Exercise Recovery](http://arxiv.org/abs/2508.00773v1)
6. [ROPE: A Novel Method for Real-Time Phase Estimation of Complex Biological Rhythms](http://arxiv.org/abs/2509.04962v2)
7. [Directional coupling detection through cross-distance vectors](http://arxiv.org/abs/2210.09000v2)
8. [Inference of Time-Evolving Coupled Dynamical Systems in the Presence of Noise](http://arxiv.org/abs/1206.1961v2)

> Moreover, we show that it can detect cardiorespiratory interaction in measured data. [1] Our analysis showed that cardiorespiratory synchronization increased post-Ironman race compared to pre-Ironman. [2] A new technique is introduced to reconstruct a nonlinear stochastic model of the cardiorespiratory interaction. [3] By modelling electrical and viscoelastic interactions within the cardiorespiratory system, we identify the conditions leading to synchronization. [4] Accurate phase estimation -- the process of assigning phase values between $0$ and $2π$ to repetitive or periodic signals -- is a cornerstone in the analysis of oscillatory signals across diverse fields, from neuroscience to robotics, where it is fundamental, e.g., to understanding coordination in neural networks, cardiorespiratory coupling, and human-robot interaction. [5]

## Research panel (R.A.I.N., offline)

- Grounding: none
- Agreed: The local library has no evidence on this question, so the room made no claims about it.
- Contested: Nothing yet. A disagreement needs evidence on the table first.
- Next move: Add two or three papers on this topic to the library and rerun the same command, or connect a local model for an open-ended meeting.

## Data

PhysioNet Fantasia 1.0.0 (ODC-By 1.0): 20 records × 10 window(s) of 600 s from t=660 s. Analyzed 190; excluded by QC 10.

Cite: Iyengar N, Peng C-K, Morin R, Goldberger AL, Lipsitz LA. Age-related alterations in the fractal scaling of cardiac interbeat interval dynamics. Am J Physiol 1996;271:R1078-R1084. Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. Circulation 2000;101(23):e215-e220.

## Limitations (pre-registered)

- The claim is relative. If neither fixed window detects slow breathers well, matching them does not mean slow breathers are detected.
- The derived window depends on the breathing-frequency estimate (dominant Welch peak, 0.0156 Hz resolution). A wrong peak gives a wrong window; the 1-8 s clamp bounds the damage.
- The synthetic controls have no rhythm, so their derived windows are arbitrary within the clamp. They check calibration, not the rule.
- The held-out windows come from the same 20 people as V3D-EXP-0001: new data, not new people. Rates weight each person equally.
- Detection means max-statistic adjusted p <= 0.05 for respiration -> heart rate. Lagged correlation ignores sign and lag 0, so this tests coupling, not direction.
- Mismatched pairs share the time into the recording, and every subject watched the same film. A film-locked common response would raise mismatched detections and count against the hypothesis.
- The holdout guarantee rests on this tool's data ledger: it shows no byte of these ranges was read through the pipeline before registration, and cannot rule out reads made outside it.
- A sibling experiment (specs/slow-breathers-6s-window.json) was registered alongside this one and is judged on the same held-out windows. Each is evaluated on its own criteria; there is no correction across the two.
- Literature retrieval uses Anna's deterministic hashing embeddings (lexical, not semantic) over arXiv metadata and abstracts only.
