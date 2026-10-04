import numpy as np
import pytest

from rain_pipeline import physio


def _header(fmt: str, n_signals: int = 2) -> physio.Header:
    names = ["RESP", "ECG", "BP"][:n_signals]
    lines = [f"rec {n_signals} 250 1000"] + [f"rec.dat {fmt} 200 12 0 0 0 0 {name}" for name in names]
    return physio.parse_header("\n".join(lines) + "\n# Age: 23\n")


def test_parse_header_reads_gain_baseline_units_and_names():
    header = physio.parse_header("f1y01 2 250 1806271\nf1y01.dat 16 2000(5)/mV 16 0 16000 -22048 0 RESP\n"
                                 "f1y01.dat 16 0 16 7 15904 168 0 ECG\n")
    assert header.fs == 250 and header.n_samples == 1806271
    resp, ecg = header.signals
    assert (resp.name, resp.gain, resp.baseline, resp.units) == ("RESP", 2000.0, 5, "mV")
    assert (ecg.gain, ecg.baseline) == (200.0, 7)  # gain 0 -> WFDB default 200; baseline defaults to ADC zero


def test_decode_format16_interleaves_frames():
    digital = np.array([[100, -200], [300, -400]], dtype="<i2")
    out = physio.decode(digital.tobytes(), _header("16"))
    np.testing.assert_allclose(out, digital / 200.0)


def _pack212(samples: np.ndarray) -> bytes:
    s = samples.astype(np.int64) & 0xFFF
    a, b = s[0::2], s[1::2]
    groups = np.column_stack([a & 0xFF, ((a >> 8) & 0x0F) | (((b >> 8) & 0x0F) << 4), b & 0xFF])
    return groups.astype(np.uint8).tobytes()


@pytest.mark.parametrize("n_signals", [2, 3])
def test_decode_format212_round_trips_signed_12_bit(n_signals):
    rng = np.random.default_rng(0)
    digital = rng.integers(-2048, 2048, size=(10, n_signals))
    out = physio.decode(_pack212(digital.ravel()), _header("212", n_signals))
    np.testing.assert_allclose(out, digital / 200.0)


def _synthetic_recording(fs=250.0, seconds=120.0, breath_hz=0.25, seed=1):
    """Respiration plus an ECG-like spike train whose rate rises during inspiration."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(fs * seconds)) / fs
    resp = np.sin(2 * np.pi * breath_hz * t)
    beats, now = [], 0.5
    while now < seconds - 0.5:
        beats.append(now)
        hr = 65 + 8 * np.sin(2 * np.pi * breath_hz * (now - 0.5))
        now += 60.0 / hr
    ecg = 0.02 * rng.standard_normal(len(t))
    for beat in beats:
        i = int(beat * fs)
        ecg[i - 2:i + 3] += [0.2, 0.6, 1.0, 0.6, 0.2]
    return t, resp, ecg, np.array(beats)


def test_r_peaks_found_within_one_sample():
    _, _, ecg, beats = _synthetic_recording()
    peaks = physio.detect_r_peaks(ecg, 250.0)
    assert len(peaks) == len(beats)
    assert np.max(np.abs(peaks / 250.0 - beats)) <= 1 / 250.0 + 1e-9


def test_paired_series_recovers_heart_rate_oscillation():
    _, resp, ecg, _ = _synthetic_recording()
    header = physio.Header("syn", 250.0, len(resp), (
        physio.Signal("RESP", "syn.dat", "16", 1.0, 0, "mV"), physio.Signal("ECG", "syn.dat", "16", 1.0, 0, "mV")))
    pair = physio.paired_series(header, np.column_stack([resp, ecg]), grid_fs=4.0, highpass_hz=0.05)
    assert pair.qc["valid_rr_fraction"] == 1.0
    assert 60 < pair.qc["mean_heart_rate_bpm"] < 70
    assert abs(np.std(pair.heart_rate) - 1.0) < 1e-9
    # HR is stamped at the end of each RR interval (~1 beat late) on top of the built-in 0.5 s lag,
    # so breathing leads heart rate by ~1.4 s: the lagged correlation peaks there.
    lags = range(13)  # 0-3 s at 4 Hz
    corr = [np.corrcoef(pair.respiration[: len(pair.respiration) - k], pair.heart_rate[k:])[0, 1] for k in lags]
    best = int(np.argmax(corr))
    assert corr[best] > 0.9
    assert 1.0 <= best / 4.0 <= 1.75
