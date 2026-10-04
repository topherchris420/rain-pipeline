"""Real physiological data: PhysioNet Fantasia (ECG + respiration at rest).

Fantasia (Iyengar et al., 1996; PhysioNet, Goldberger et al., 2000) holds 120
minutes of resting ECG and respiration per subject at 250 Hz, under the Open
Data Commons Attribution License v1.0. Only the pre-registered segment of each
record is fetched, with an HTTP byte-range request, and every downloaded byte
is hashed into the run's provenance and cached under ``data/cache``.

From the raw signals this module derives two series on a common grid:
respiration (low-passed) and instantaneous heart rate from detected R peaks.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import requests
from scipy.ndimage import median_filter
from scipy.signal import butter, filtfilt, find_peaks, sosfiltfilt

FANTASIA = "https://physionet.org/files/fantasia/1.0.0/"
USER_AGENT = "rain-pipeline/0.1 (research; byte-range fetch of Fantasia segments)"


@dataclass(frozen=True)
class Signal:
    name: str
    file: str
    fmt: str
    gain: float
    baseline: int
    units: str


@dataclass(frozen=True)
class Header:
    record: str
    fs: float
    n_samples: int
    signals: tuple[Signal, ...]


_GAIN_RE = re.compile(r"^(?P<gain>[-+0-9.eE]+)?(?:\((?P<baseline>-?\d+)\))?(?:/(?P<units>\S+))?$")


def parse_header(text: str) -> Header:
    """Parse a WFDB ``.hea`` header (single-segment records only)."""
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    record, n_signals, fs, n_samples = lines[0].split()[:4]
    signals = []
    for line in lines[1 : 1 + int(n_signals)]:
        fields = line.split()
        match = _GAIN_RE.match(fields[2])
        if match is None:
            raise ValueError(f"unreadable gain field {fields[2]!r}")
        gain = float(match["gain"] or 0) or 200.0  # WFDB: gain 0 means the default 200
        adc_zero = int(fields[4]) if len(fields) > 4 else 0
        baseline = int(match["baseline"]) if match["baseline"] is not None else adc_zero
        description = " ".join(fields[8:]) if len(fields) > 8 else f"signal{len(signals)}"
        signals.append(Signal(description, fields[0], fields[1], gain, baseline, match["units"] or "mV"))
    return Header(record, float(fs.split("/")[0]), int(n_samples), tuple(signals))


def storage_format(header: Header) -> str:
    formats = {s.fmt for s in header.signals}
    if len(formats) != 1 or not formats <= {"16", "212"} or len({s.file for s in header.signals}) != 1:
        raise ValueError(f"{header.record}: only single-file WFDB format 16 or 212 is supported")
    return formats.pop()


def bytes_per_sample(fmt: str) -> float:
    return 2.0 if fmt == "16" else 1.5


def decode(raw: bytes, header: Header) -> np.ndarray:
    """Interleaved frames (format 16 or 212) -> physical units, shape (n, n_signals)."""
    fmt = storage_format(header)
    n = len(header.signals)
    if fmt == "16":
        digital = np.frombuffer(raw, dtype="<i2").astype(np.int64)
    else:
        # Format 212: each 3-byte group packs two 12-bit two's-complement samples.
        groups = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
        first = groups[:, 0] | ((groups[:, 1] & 0x0F) << 8)
        second = groups[:, 2] | ((groups[:, 1] & 0xF0) << 4)
        digital = np.column_stack([first, second]).ravel()
        digital = np.where(digital > 2047, digital - 4096, digital)
    digital = digital.reshape(-1, n).astype(float)
    gains = np.array([s.gain for s in header.signals])
    baselines = np.array([s.baseline for s in header.signals])
    return (digital - baselines) / gains


def _get(url: str, **headers: str) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": USER_AGENT, **headers}, timeout=60)
    response.raise_for_status()
    return response


def fetch_segment(record: str, start_s: float, duration_s: float, cache_dir: Path) -> tuple[Header, np.ndarray, dict]:
    """Fetch one segment of a Fantasia record (cached) and return provenance for it."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    header_path = cache_dir / f"{record}.hea"
    if not header_path.exists():
        header_path.write_bytes(_get(FANTASIA + f"{record}.hea").content)
    header_bytes = header_path.read_bytes()
    header = parse_header(header_bytes.decode("ascii"))

    # Even frame counts keep format-212 sample pairs byte-aligned for any signal count.
    first = 2 * int(round(start_s * header.fs / 2))
    count = 2 * int(round(duration_s * header.fs / 2))
    if first + count > header.n_samples:
        raise ValueError(f"{record}: segment ends past the record ({header.n_samples} samples)")
    frame = bytes_per_sample(storage_format(header)) * len(header.signals)
    byte_range = (int(first * frame), int((first + count) * frame) - 1)
    expected = byte_range[1] - byte_range[0] + 1

    segment_path = cache_dir / f"{record}_{first}_{count}.dat"
    url = FANTASIA + header.signals[0].file
    if not segment_path.exists():
        response = _get(url, Range=f"bytes={byte_range[0]}-{byte_range[1]}")
        if response.status_code != 206 or len(response.content) != expected:
            raise RuntimeError(f"{record}: server did not honour the byte range")
        segment_path.write_bytes(response.content)
    raw = segment_path.read_bytes()

    provenance = {
        "record": record,
        "url": url,
        "byte_range": list(byte_range),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "header_url": FANTASIA + f"{record}.hea",
        "header_sha256": hashlib.sha256(header_bytes).hexdigest(),
        "fs_hz": header.fs,
        "start_s": start_s,
        "duration_s": duration_s,
    }
    return header, decode(raw, header), provenance


def detect_r_peaks(ecg: np.ndarray, fs: float) -> np.ndarray:
    """Band-pass QRS energy, polarity-corrected, with a 330 ms refractory period."""
    b, a = butter(3, [5.0 / (fs / 2), 20.0 / (fs / 2)], btype="band")
    filtered = filtfilt(b, a, ecg)
    if np.percentile(-filtered, 99.5) > np.percentile(filtered, 99.5):
        filtered = -filtered
    height = 0.35 * np.percentile(filtered, 99.5)
    peaks, _ = find_peaks(filtered, height=height, distance=int(0.33 * fs))
    return peaks


@dataclass(frozen=True)
class PairedSeries:
    record: str
    respiration: np.ndarray   # standardized
    heart_rate: np.ndarray    # standardized
    fs: float
    qc: dict[str, Any]


def paired_series(header: Header, data: np.ndarray, *, grid_fs: float, highpass_hz: float) -> PairedSeries:
    """Respiration and instantaneous heart rate on one uniform grid."""
    names = [s.name.upper() for s in header.signals]
    if "ECG" not in names or "RESP" not in names:
        raise ValueError(f"{header.record}: needs ECG and RESP signals, has {names}")
    fs = header.fs
    ecg = data[:, names.index("ECG")]
    resp = data[:, names.index("RESP")]

    peaks = detect_r_peaks(ecg, fs)
    beat_t = peaks / fs
    rr = np.diff(beat_t)
    rr_t = beat_t[1:]
    local = median_filter(rr, size=11, mode="nearest")
    valid = (rr >= 0.33) & (rr <= 2.0) & (np.abs(rr - local) <= 0.3 * local)

    t0 = max(rr_t[0], 2.0)
    t1 = min(rr_t[-1], len(resp) / fs - 2.0)
    grid = np.arange(t0, t1, 1.0 / grid_fs)
    heart_rate = np.interp(grid, rr_t[valid], 60.0 / rr[valid])

    lowpass = butter(4, 1.0 / (fs / 2), btype="low", output="sos")
    respiration = np.interp(grid, np.arange(len(resp)) / fs, sosfiltfilt(lowpass, resp))

    highpass = butter(2, highpass_hz / (grid_fs / 2), btype="high", output="sos")
    respiration = _zscore(sosfiltfilt(highpass, respiration))
    heart_rate_z = _zscore(sosfiltfilt(highpass, heart_rate))

    qc = {
        "beats": int(len(peaks)),
        "valid_rr_fraction": float(np.mean(valid)) if len(valid) else 0.0,
        "mean_heart_rate_bpm": float(np.mean(60.0 / rr[valid])) if valid.any() else None,
        "grid_samples": int(len(grid)),
    }
    return PairedSeries(header.record, respiration, heart_rate_z, grid_fs, qc)


def _zscore(x: np.ndarray) -> np.ndarray:
    return (x - np.mean(x)) / np.std(x)
