"""Build a matplotlib figure from a `Plot` spec and an `AnalysisResult`.

The same spec drives the Origin bridge, so what you see here is what lands in Origin.
Nothing in this module touches Qt, so figures can be rendered headlessly for tests and
batch exports.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from ..core.curves import AnalysisResult
from ..core.measurements import Measurement, Plot, Series
from . import style as S

__all__ = ["PlotData", "build_plot_data", "render_figure", "save_figure",
           "annotate_metrics", "figure_for", "free_corners"]

_LEGEND_INSIDE_MAX = 4      # above this, the legend goes outside the axes


@dataclass
class PlotData:
    """A plot resolved against real data: every series has numbers and a style."""
    plot: Plot
    title: str
    x_axis: str
    y_axis: str
    xscale: str
    yscale: str
    labels: list[str]
    x: list[np.ndarray]
    y: list[np.ndarray]
    styles: list[S.SeriesStyle]
    roles: list[str]
    note: str = ""

    def __len__(self) -> int:
        return len(self.labels)

    @property
    def is_empty(self) -> bool:
        return not self.labels or all(a.size == 0 for a in self.x)


# ---------------------------------------------------------------------------
# resolve a spec against a result
# ---------------------------------------------------------------------------
def build_plot_data(plot: Plot, result: AnalysisResult, *, theme: str = "light",
                    palette_name: str | None = None, title: str | None = None) -> PlotData:
    """Expand a `Plot` spec into concrete traces, assigning colours and symbols."""
    expanded: list[tuple[str, str, str]] = []          # (curve key, label, role)
    for series in plot.series:
        if series.curve == "*":
            for i, key in enumerate(result.curves, start=1):
                expanded.append((key, key if series.label in ("", "Cycle") else
                                 f"{series.label} {i}", series.role))
        elif series.curve in result.curves:
            expanded.append((series.curve, series.label, series.role))

    hint_by_curve = {s.curve: s.style for s in plot.series}
    default_hint = plot.series[0].style if plot.series else "scatter"

    labels, xs, ys, styles, roles = [], [], [], [], []
    data_index = 0
    last_data_index: int | None = None
    data_slots: dict[str, int] = {}                   # curve stem -> palette slot
    for key, label, role in expanded:
        x, y = result.curves[key]
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        if x.size == 0 or y.size == 0:
            continue
        hint = hint_by_curve.get(key, default_hint)
        if role == "fit":
            # A fit takes the colour of the data it fits, so "elastic fit" is drawn in the
            # colour of "elastic data" even when several fits share one figure. With a
            # single data series every fit belongs to it; with several, a fit that matches
            # none of them (a combined "total" curve, say) gets a colour of its own.
            parent = data_slots.get(_stem(key))
            if parent is None and len(data_slots) == 1:
                parent = last_data_index
            st = S.style_for(data_index, "fit", palette_name=palette_name, label=label,
                             parent=parent, theme=theme, style_hint=hint)
        else:
            st = S.style_for(data_index, role, palette_name=palette_name, label=label,
                             theme=theme, style_hint=hint)
            data_slots[_stem(key)] = data_index
            last_data_index = data_index
            data_index += 1
        labels.append(label)
        xs.append(x)
        ys.append(y)
        styles.append(st)
        roles.append(role)

    # A log axis cannot show zero or negative values; fall back rather than plot nothing.
    xscale = _safe_scale(plot.xscale, xs)
    yscale = _safe_scale(plot.yscale, ys)

    return PlotData(plot=plot, title=title or plot.title, x_axis=plot.x_axis,
                    y_axis=plot.y_axis, xscale=xscale, yscale=yscale, labels=labels,
                    x=xs, y=ys, styles=styles, roles=roles, note=plot.note)


_ROLE_WORDS = {"fit", "data", "measured", "curve", "points", "plot", "branch"}


def _stem(curve_key: str) -> str:
    """"elastic fit" and "elastic data" share the stem "elastic", so they share a colour."""
    words = [w for w in curve_key.lower().replace("-", " ").split() if w not in _ROLE_WORDS]
    return " ".join(words) or curve_key.lower()


def _safe_scale(requested: str, arrays: Sequence[np.ndarray]) -> str:
    if requested != "log":
        return requested
    for a in arrays:
        finite = a[np.isfinite(a)]
        if finite.size and finite.min() <= 0:
            return "linear"
    return "log"


def figure_for(measurement: Measurement, result: AnalysisResult, plot_id: str | None = None,
               **kwargs):
    """Convenience: the first (or named) plot of a measurement, rendered."""
    plots = {p.id: p for p in measurement.plots}
    if not plots:
        raise ValueError(f"{measurement.name} has no plots")
    plot = plots[plot_id] if plot_id else measurement.plots[0]
    data = build_plot_data(plot, result, theme=kwargs.pop("theme", "light"),
                           palette_name=kwargs.pop("palette_name", None))
    return render_figure(data, **kwargs)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
def render_figure(data: PlotData, *, theme: str = "light", size: str = "screen",
                  figure=None, legend: bool = True, show_note: bool = True,
                  tight: bool = True):
    """Draw `data` onto a new or supplied matplotlib Figure and return it."""
    import matplotlib
    from matplotlib.figure import Figure

    rc = S.apply_matplotlib_style(theme, size)
    t = S.THEMES.get(theme, S.THEMES["light"])

    with matplotlib.rc_context(rc):
        if figure is None:
            figure = Figure(figsize=rc["figure.figsize"], dpi=rc["figure.dpi"])
        figure.clear()
        figure.patch.set_facecolor(t.background)
        ax = figure.add_subplot(111)
        _apply_axes_style(ax, rc, t)

        if data.is_empty:
            ax.text(0.5, 0.5, "No data to plot", ha="center", va="center",
                    transform=ax.transAxes, color=t.muted, fontsize=11)
            ax.set_axis_off()
            return figure

        for x, y, st in zip(data.x, data.y, data.styles):
            ok = np.isfinite(x) & np.isfinite(y)
            ax.plot(x[ok], y[ok], **st.mpl_kwargs(background=t.background))

        ax.set_title(data.title)
        ax.set_xlabel(data.x_axis)
        ax.set_ylabel(data.y_axis)
        if data.xscale == "log":
            ax.set_xscale("log")
        if data.yscale == "log":
            ax.set_yscale("log")
        ax.grid(True, which="major", color=t.grid, linewidth=0.7, alpha=0.9)
        if data.xscale == "log" or data.yscale == "log":
            ax.grid(True, which="minor", color=t.grid, linewidth=0.45, alpha=0.5)

        if legend and len(data) > 1:
            if len(data) > _LEGEND_INSIDE_MAX:
                # Too many traces to sit over the data without hiding it: move it outside.
                leg = ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0),
                                borderaxespad=0.0, fontsize=rc["legend.fontsize"])
            else:
                free = free_corners(data, ax)
                # The metrics box is placed later into free[0]; keep the legend out of it.
                leg = ax.legend(loc=free[1] if len(free) > 1 else "best",
                                fontsize=rc["legend.fontsize"])
            leg.get_frame().set_facecolor(t.background)
            leg.get_frame().set_edgecolor(t.grid)
            leg.get_frame().set_linewidth(0.8)
            for text in leg.get_texts():
                text.set_color(t.foreground)

        if show_note and data.note:
            figure.text(0.012, 0.012, data.note, fontsize=7.6, color=t.muted,
                        ha="left", va="bottom", style="italic")
        if tight:
            try:
                figure.tight_layout(pad=0.9, rect=(0, 0.035 if data.note else 0, 1, 1))
            except Exception:                      # noqa: BLE001 - layout is best-effort
                pass
    return figure


def _apply_axes_style(ax, rc: dict, theme: S.Theme) -> None:
    ax.set_facecolor(theme.background)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.foreground)
        ax.spines[side].set_linewidth(1.0)
    ax.tick_params(colors=theme.foreground, which="both")
    ax.xaxis.label.set_color(theme.foreground)
    ax.yaxis.label.set_color(theme.foreground)
    ax.title.set_color(theme.foreground)


CORNERS = ("upper left", "upper right", "lower left", "lower right")


def free_corners(data: PlotData, ax=None) -> list[str]:
    """The four corners, emptiest first, so boxes land where the data is not.

    Counts how many plotted points fall inside each corner's quadrant in axes
    coordinates. Beats matplotlib's `loc="best"` here because it lets the legend and the
    metrics box agree on who gets which corner instead of both choosing the same one.
    """
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    for x, y in zip(data.x, data.y):
        ok = np.isfinite(x) & np.isfinite(y)
        if not ok.any():
            continue
        xmin, xmax = min(xmin, float(x[ok].min())), max(xmax, float(x[ok].max()))
        ymin, ymax = min(ymin, float(y[ok].min())), max(ymax, float(y[ok].max()))
    if not all(map(math.isfinite, (xmin, xmax, ymin, ymax))) or xmax == xmin or ymax == ymin:
        return list(CORNERS)

    log_x = data.xscale == "log" and xmin > 0
    log_y = data.yscale == "log" and ymin > 0
    counts = dict.fromkeys(CORNERS, 0)
    for x, y in zip(data.x, data.y):
        ok = np.isfinite(x) & np.isfinite(y)
        if not ok.any():
            continue
        u = _normalise(x[ok], xmin, xmax, log_x)
        v = _normalise(y[ok], ymin, ymax, log_y)
        # 45 % of each axis: wide enough that a box in an "empty" corner really is clear.
        for name, mask in (("upper left", (u < 0.45) & (v > 0.55)),
                           ("upper right", (u > 0.55) & (v > 0.55)),
                           ("lower left", (u < 0.45) & (v < 0.45)),
                           ("lower right", (u > 0.55) & (v < 0.45))):
            counts[name] += int(mask.sum())
    return sorted(CORNERS, key=lambda c: (counts[c], CORNERS.index(c)))


def _normalise(values: np.ndarray, lo: float, hi: float, log: bool) -> np.ndarray:
    if log:
        values, lo, hi = np.log10(np.clip(values, 1e-300, None)), math.log10(lo), math.log10(hi)
    return (values - lo) / (hi - lo) if hi > lo else np.zeros_like(values)


def annotate_metrics(figure, metrics: Iterable, *, theme: str = "light", maximum: int = 4,
                     corner: str | None = None, data: PlotData | None = None) -> None:
    """Drop a small results box onto a figure — the bit reviewers always ask for.

    With no `corner`, the box goes wherever the data leaves room.
    """
    from ..core.units import format_value

    t = S.THEMES.get(theme, S.THEMES["light"])
    # A narrow single-column figure cannot hold a legend and a four-line box as well as the
    # data. Shrink the box rather than squeeze the axes into nothing.
    width_in = figure.get_size_inches()[0]
    maximum = min(maximum, 4 if width_in >= 6.0 else (3 if width_in >= 4.5 else 2))
    lines = []
    for m in metrics:
        if len(lines) >= maximum:
            break
        if m.value is None or (isinstance(m.value, float) and not math.isfinite(m.value)):
            continue
        unit = f" {m.unit}" if m.unit and m.unit != "-" else ""
        lines.append(f"{m.name} = {format_value(m.value)}{unit}")
    if not lines or not figure.axes:
        return
    ax = figure.axes[0]
    if corner is None:
        corner = free_corners(data)[0] if data is not None else "upper left"
    pad = 0.028
    x = pad if "left" in corner else 1.0 - pad
    y = 1.0 - pad if "upper" in corner else pad

    # Keep the box inside the panel: on a single-column figure a long metric name would
    # otherwise run off the page.
    fontsize = 8.2
    budget = max(18, int(figure.get_size_inches()[0] * 72 * 0.52 / (fontsize * 0.54)))
    lines = [ln if len(ln) <= budget else ln[:budget - 1].rstrip() + "…" for ln in lines]

    ax.text(x, y, "\n".join(lines), transform=ax.transAxes,
            ha="right" if "right" in corner else "left",
            va="bottom" if "lower" in corner else "top",
            fontsize=fontsize, color=t.foreground, linespacing=1.45, zorder=5,
            bbox={"boxstyle": "round,pad=0.45", "facecolor": t.panel,
                  "edgecolor": t.grid, "alpha": 0.94, "linewidth": 0.8})


def save_figure(figure, path: str | Path, *, dpi: str | int = "print",
                transparent: bool = False) -> Path:
    """Write a figure to PNG / PDF / SVG / EPS / TIFF, picking the format from the suffix."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    resolution = S.EXPORT_DPI.get(dpi, dpi) if isinstance(dpi, str) else dpi
    figure.savefig(p, dpi=resolution, transparent=transparent,
                   facecolor="none" if transparent else figure.get_facecolor(),
                   bbox_inches="tight", pad_inches=0.06)
    return p
