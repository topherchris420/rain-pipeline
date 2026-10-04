# V3D-EXP-0001 V3D-EXP-0001-RUN-0001: PASSED

**Does DRR recover respiration-to-heart-rate coupling (RSA) in resting young adults?**

- Question: Does breathing drive heart rate at rest, and can Dynamic Resonance Rooting recover that respiratory sinus arrhythmia coupling from real recordings?
- Hypothesis: In at least 80% of 10-minute resting recordings from healthy young adults (PhysioNet Fantasia), DRR detects respiration -> heart-rate coupling (max-statistic adjusted p <= 0.05, lags 0.25-3 s), given that mismatched-subject pairs are detected in at most 25% and the synthetic controls behave as calibrated.
- Verdict (assigned by R.A.I.N. `rain-criteria/v1`): supported
- All 1 success criteria held and no failure criterion triggered.
- R.A.I.N. re-verification: OK (1 run(s) re-derived from stored data)

## Criteria

| Id | Metric | Needs | Observed | Holds |
|---|---|---|---|---|
| G1 | `records_analyzed` | >= 16 | 20 | True |
| G2 | `positive_control_detection_rate` | >= 0.9 | 1 | True |
| G3 | `synthetic_null_false_positive_rate` | <= 0.15 | 0.05 | True |
| G4 | `mismatched_detection_rate` | <= 0.25 | 0.05 | True |
| S1 | `coupling_detection_rate` | >= 0.8 | 0.9 | True |
| F1 | `coupling_detection_rate` | < 0.5 | 0.9 | False |

## Literature (Anna)

Record `f8c6ae4e5d37d0928f437e7e8f30299c67a4bcc02e2060f130a68d293a07bdd3`, excerpts re-verified: {'verified': 5, 'relocated': 0, 'drifted': 0, 'missing-document': 0, 'missing-field': 0, 'invalid-excerpt': 0}

1. [Mathematical and Preclinical Investigation of Respiratory Sinus Arrhythmia Effects on Cardiac Output](http://arxiv.org/abs/2004.11325v1)
2. [Cardiorespiratory coupling improves cardiac pumping efficiency in heart failure](http://arxiv.org/abs/2507.00597v1)
3. [Analysis of Respiratory Sinus Arrhythmia with Neural Networks](http://arxiv.org/abs/2609.05698v1)
4. [Disentangling Respiratory Sinus Arrhythmia in Heart Rate Variability Records](http://arxiv.org/abs/1802.00683v1)
5. [Synchronization-dissipation dynamics in the cardiorespiratory system](http://arxiv.org/abs/2603.23259v1)
6. [Contact Sensors to Remote Cameras: Quantifying Cardiorespiratory Coupling in High-Altitude Exercise Recovery](http://arxiv.org/abs/2508.00773v1)
7. [Buffering blood pressure fluctuations by respiratory sinus arrhythmia may in fact enhance them: a theoretical analysis](http://arxiv.org/abs/1007.2229v1)
8. [RespEar: Earable-Based Robust Respiratory Rate Monitoring](http://arxiv.org/abs/2407.06901v1)

> the respiratory sinus arrhythmia. [1] Here we examine the functional significance of this coupling which is observed in respiratory sinus arrhythmia (RSA). [2] Respiratory sinus arrhythmia (RSA) is heart rate variability in synchrony with respiration although its functional significance not clear. [3] Different measures of heart rate variability and particularly of respiratory sinus arrhythmia are widely used in research and clinical applications. [4] By leveraging the unique properties of in-ear microphones in earbuds, RespEar enables the use of Respiratory Sinus Arrhythmia (RSA) and Locomotor Respiratory Coupling (LRC), physiological couplings between cardiovascular activity, gait and respiration, to indirectly determine RR. [5]

## Research panel (R.A.I.N., offline)

- Grounding: strong
- Agreed: The library speaks to this directly: 7 papers cover 'drive', 'heart', 'rate' and 'rest', led by 04-disentangling-respiratory-sinus-arrhythmia-in-heart-rate-var.
- Contested: Luca reads the shared 'clinical' in 04-disentangling-respiratory-sinus-arrhythmia-in-heart-rate-var and 07-buffering-blood-pressure-fluctuations-by-respiratory-sinus-a as real structure; Elena reads it as unreplicated until an outside source reproduces it.
- Next move: Write one falsifiable prediction for this question and the measurement that would refute it.

Full transcript: `panel_meeting.md`.

## Data

PhysioNet Fantasia 1.0.0 (ODC-By 1.0): 20 records, 600 s from t=60 s. Excluded by QC: none.

Cite: Iyengar N, Peng C-K, Morin R, Goldberger AL, Lipsitz LA. Age-related alterations in the fractal scaling of cardiac interbeat interval dynamics. Am J Physiol 1996;271:R1078-R1084. Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. Circulation 2000;101(23):e215-e220.

## Limitations (pre-registered)

- Lagged correlation ignores sign and lag 0, and respiration and heart rate share one rhythm, so the reverse direction may score as high: this tests coupling, not direction.
- Fantasia subjects are healthy young adults in supine rest watching the film Fantasia; nothing here generalizes to other ages, conditions or postures.
- R peaks come from a simple band-pass detector; records below the QC threshold are excluded, not repaired.
- Respiratory sinus arrhythmia is established physiology; this experiment tests whether DRR recovers it, not whether it exists.
- Literature retrieval uses Anna's deterministic hashing embeddings (lexical, not semantic) over arXiv metadata and abstracts only.
