"""Static figures for run reports.

One figure per ``lag_window`` report: detection by breathing stratum (grouped
columns, one per lag-window arm) and by breathing frequency (one line per
arm). ``window_lengths`` draws one more, across explorations: detection by
window length. Colours are a validated four-slot categorical palette in fixed
arm order; text stays in ink colours and every column or line carries a label,
so identity never rests on colour alone. The numbers behind every figure are
in the reports it is drawn from.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

SURFACE, INK, SECONDARY, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
# Blue, orange, aqua, yellow: the first three pass all-pairs CVD checks on this surface, all four the adjacent
# pairs that lines and grouped columns put side by side. Aqua and yellow sit under 3:1 contrast, so marks are labelled.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
DPI = 200
PX = DPI / 100  # device pixels per CSS-like pixel


def arm_label(arm: dict[str, Any]) -> str:
    if arm.get("rule") == "half_period":
        return "Half-period window (from the breathing rhythm)"
    return f"{arm['max_lag_s']:g} s window"


def render(report: dict[str, Any], path: Path, note: str = "") -> dict[str, Any] | None:
    """Write the figure and return its artifact reference, or None when the study has no figure."""
    settings = report.get("settings", {})
    arms: dict[str, dict[str, Any]] = settings.get("arms", {})
    if report.get("study") != "lag_window" or not report.get("windows") or not 0 < len(arms) <= len(SERIES):
        return None

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath
    from matplotlib.ticker import PercentFormatter

    from matplotlib import font_manager

    installed = {font.name for font in font_manager.fontManager.ttflist}  # naming a missing font logs a warning per text
    plt.rcParams["font.family"] = [name for name in ("Segoe UI", "DejaVu Sans") if name in installed] or ["sans-serif"]
    measurements, rows, alpha = report["measurements"], report["windows"], settings["alpha"]
    strata: dict[str, dict[str, float]] = settings["strata"]
    colors = dict(zip(arms, SERIES))

    fig = plt.figure(figsize=(11, 4.7), dpi=DPI, facecolor=SURFACE)
    left = fig.add_axes([0.06, 0.17, 0.40, 0.58])
    right = fig.add_axes([0.56, 0.17, 0.40, 0.58])
    for ax in (left, right):
        ax.set_facecolor(SURFACE)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(BASELINE)
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", colors=MUTED, labelcolor=SECONDARY, labelsize=8.5, length=0)
        ax.set_ylim(0, 1.22)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))

    # Left: subject-balanced detection per stratum, plus the mismatched-subject control.
    groups = [(f"{name.capitalize()} breathing\n{measurements[f'{name}_windows']} windows, "
               f"{measurements[f'{name}_subjects']} people",
               [measurements[f"{name}_detection_rate_{arm}"] for arm in arms]) for name in strata]
    groups.append(("Mismatched people\n(control: should stay low)",
                   [measurements[f"mismatched_detection_rate_{arm}"] for arm in arms]))
    left.set_xlim(-0.6, len(groups) - 0.4)
    inverse = left.transData.inverted()
    x_px, y_px = (inverse.transform((PX, PX)) - inverse.transform((0, 0)))
    # Columns stand apart (not touching) so that a "100%" label fits over each one.
    width, gap, radius_x, radius_y = 24 * x_px, 14 * x_px, 4 * x_px, 4 * y_px
    for g, (_, values) in enumerate(groups):
        for a, (arm, value) in enumerate(zip(arms, values)):
            x0 = g + (a - len(arms) / 2) * (width + gap) + gap / 2
            if value is None:
                left.text(x0 + width / 2, 6 * y_px, "n/a", ha="center", va="bottom", fontsize=8, color=MUTED)
                continue
            ry = min(radius_y, value)
            top = max(value, 1.5 * y_px)  # a zero still shows as a sliver on the baseline
            vertices = [(x0, 0), (x0, top - ry), (x0, top), (x0 + radius_x, top), (x0 + width - radius_x, top),
                        (x0 + width, top), (x0 + width, top - ry), (x0 + width, 0), (x0, 0)]
            codes = [MplPath.MOVETO, MplPath.LINETO, MplPath.CURVE3, MplPath.CURVE3, MplPath.LINETO,
                     MplPath.CURVE3, MplPath.CURVE3, MplPath.LINETO, MplPath.CLOSEPOLY]
            left.add_patch(PathPatch(MplPath(vertices, codes), facecolor=colors[arm], edgecolor="none"))
            left.text(x0 + width / 2, top + 5 * y_px, f"{value:.0%}", ha="center", va="bottom", fontsize=8.5,
                      color=INK)
    left.set_xticks(range(len(groups)))
    left.set_xticklabels([label for label, _ in groups], linespacing=1.5)
    left.set_title("By breathing stratum (each person weighted equally)", loc="left", fontsize=9.5,
                   color=SECONDARY, pad=6)

    # Right: share of windows detected, by breathing-frequency bin.
    step = 1 / 32  # two Welch bins at 4 Hz with 64 s segments
    bins: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row["respiratory_frequency_hz"]:
            bins.setdefault(math.floor(row["respiratory_frequency_hz"] / step + 1e-9), []).append(row)
    minimum = 3 if len(rows) >= 60 else 1
    kept = sorted(index for index, members in bins.items() if len(members) >= minimum)
    centers = [(index + 0.5) * step for index in kept]
    if centers:
        right.set_xlim(centers[0] - step, centers[-1] + step)
        right.set_xticks(centers)
        right.set_xticklabels([f"{c:.2f}\nn={len(bins[i])}" for c, i in zip(centers, kept)], linespacing=1.5)
    dodge = 9 * (right.transData.inverted().transform((PX, 0)) - right.transData.inverted().transform((0, 0)))[0]
    for a, arm in enumerate(arms):
        shares = [sum(r["arms"][arm]["forward_adjusted_p"] <= alpha for r in bins[i]) / len(bins[i]) for i in kept]
        # Arms that agree would hide each other, so each sits a few pixels to the side.
        shifted = [c + (a - (len(arms) - 1) / 2) * dodge for c in centers]
        right.plot(shifted, shares, color=colors[arm], linewidth=1.5, marker="o", markersize=7,
                   markeredgecolor=SURFACE, markeredgewidth=1.5, solid_capstyle="round", clip_on=False, zorder=3)
    for bounds in strata.values():
        edge = bounds.get("below_hz")
        if edge and centers and centers[0] - step < edge < centers[-1] + step:
            right.axvline(edge, ymax=1.1 / 1.22, color=BASELINE, linewidth=0.8, zorder=1)
            right.text(edge, 1.15, f"slower than {edge:.3g} Hz  |  faster", ha="center", va="center",
                       fontsize=8, color=MUTED)
    right.set_xlabel("Breathing frequency (Hz) and number of windows", fontsize=8.5, color=SECONDARY, labelpad=6)
    right.set_title("By breathing frequency (share of windows detected)", loc="left", fontsize=9.5,
                    color=SECONDARY, pad=6)

    fig.text(0.06, 0.945, "Breathing-to-heart-rate coupling detected, by lag window", fontsize=13,
             fontweight="bold", color=INK, va="center")
    if note:
        fig.text(0.06, 0.885, note, fontsize=9, color=SECONDARY, va="center")
    handles = [Line2D([], [], marker="s", linestyle="none", markersize=8, color=colors[arm]) for arm in arms]
    legend = fig.legend(handles, [arm_label(arms[arm]) for arm in arms], loc="upper right",
                        bbox_to_anchor=(0.965, 0.99), ncol=1, frameon=False, fontsize=8.5,
                        handletextpad=0.4, labelspacing=0.35)
    for text in legend.get_texts():
        text.set_color(SECONDARY)

    fig.savefig(path, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    data = path.read_bytes()
    return {"name": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _window_seconds(report: dict[str, Any]) -> float:
    starts = sorted({row["start_s"] for row in report["windows"] if row["record"] == report["windows"][0]["record"]})
    return min(b - a for a, b in zip(starts, starts[1:])) if len(starts) > 1 else float("nan")


def window_lengths(reports: list[dict[str, Any]], path: Path, note: str = "") -> dict[str, Any]:
    """Detection by window length, one line per arm, from explorations that differ only in window length."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.lines import Line2D
    from matplotlib.ticker import PercentFormatter

    installed = {font.name for font in font_manager.fontManager.ttflist}
    plt.rcParams["font.family"] = [name for name in ("Segoe UI", "DejaVu Sans") if name in installed] or ["sans-serif"]
    reports = sorted(reports, key=_window_seconds)
    arms: dict[str, dict[str, Any]] = reports[0]["settings"]["arms"]
    colors = dict(zip(arms, SERIES))
    seconds = [_window_seconds(r) for r in reports]
    x = [math.log(s) for s in seconds]

    def values(metric: str, arm: str) -> list[float]:
        return [r["measurements"][f"{metric}_{arm}"] for r in reports]

    detected = [v for metric in ("normal_detection_rate", "slow_detection_rate") for arm in arms
                for v in values(metric, arm)]
    mismatched = [v for arm in arms for v in values("mismatched_detection_rate", arm)]
    floor = math.floor(min(detected) * 10 - 0.5) / 10  # one scale for both detection panels
    ceiling = max(0.1, math.ceil(max(mismatched) * 20) / 20)
    panels = [("normal_detection_rate", "Own heart rate, normal breathing", (floor, 1.0)),
              ("slow_detection_rate", "Own heart rate, slow breathing", (floor, 1.0)),
              ("mismatched_detection_rate", "Another person's heart rate (should stay low)", (0.0, ceiling))]

    fig = plt.figure(figsize=(11, 4.6), dpi=DPI, facecolor=SURFACE)
    span = x[-1] - x[0]
    for p, (metric, title, (low, high)) in enumerate(panels):
        ax = fig.add_axes([0.05 + p * 0.325, 0.13, 0.27, 0.56])
        ax.set_facecolor(SURFACE)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(BASELINE)
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", colors=MUTED, labelcolor=SECONDARY, labelsize=8.5, length=0)
        ax.set_ylim(low, high)
        ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        ax.set_xlim(x[0] - 0.75 * span, x[-1] + 0.06 * span)  # room on the left for the line labels
        ax.set_xticks(x)
        ax.set_xticklabels([f"{s / 60:g} min" for s in seconds])
        ax.set_title(title, loc="left", fontsize=9.5, color=SECONDARY, pad=8)
        ends = []
        for arm in arms:
            series = values(metric, arm)
            ax.plot(x, series, color=colors[arm], linewidth=2, marker="o", markersize=7, markeredgecolor=SURFACE,
                    markeredgewidth=1.5, solid_capstyle="round", clip_on=False, zorder=3)
            ends.append((series[0], arm))
        # Direct labels beside the shortest window, where the lines spread most. Lines that start too close to
        # label apart share one label, so a label never sits beside another line's point.
        clusters: list[list[tuple[float, str]]] = []
        for value, arm in sorted(ends):
            if clusters and value - clusters[-1][-1][0] < (high - low) * 0.07:
                clusters[-1].append((value, arm))
            else:
                clusters.append([(value, arm)])
        for members in clusters:
            names = {arm for _, arm in members}
            ax.text(x[0] - 0.05 * span, sum(v for v, _ in members) / len(members),
                    ", ".join(arm for arm in arms if arm in names), ha="right", va="center", fontsize=8,
                    color=SECONDARY)
    fig.text(0.05, 0.945, "Coupling detected, by window length and lag window", fontsize=13, fontweight="bold",
             color=INK, va="center")
    if note:
        fig.text(0.05, 0.885, note, fontsize=9, color=SECONDARY, va="center")
    handles = [Line2D([], [], color=colors[arm], linewidth=2, marker="o", markersize=6) for arm in arms]
    legend = fig.legend(handles, [f"{arm}: {arm_label(arms[arm]).replace(' window', '')}" for arm in arms],
                        loc="upper left", bbox_to_anchor=(0.045, 0.855), ncol=len(arms), frameon=False,
                        fontsize=8.5, handletextpad=0.4, columnspacing=1.6)
    for text in legend.get_texts():
        text.set_color(SECONDARY)
    fig.savefig(path, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    data = path.read_bytes()
    return {"name": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
