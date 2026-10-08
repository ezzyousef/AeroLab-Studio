"""Export a whole analysis session to one formatted Excel workbook.

The workbook is meant to be handed to a supervisor as-is:

    Summary        every metric of every run, one row each, grouped by sample
    Validation     the equation library recomputing the published numbers
    <sample>       per-run sheet: metrics, then the raw and derived curves
    Charts         native Excel charts (real charts, not pasted pictures)
    Provenance     versions, files, options and timestamps, so a result can be retraced

Written with xlsxwriter, which is the only writer that can create native charts.
"""
from __future__ import annotations

import math
import platform
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from ..core.curves import AnalysisResult
from ..core.measurements import Measurement, Plot
from ..viz import style as S

__all__ = ["RunRecord", "ExcelReport", "write_workbook"]

MAX_CHART_POINTS = 1200         # longer curves are charted from an evenly thinned copy
SHEET_NAME_LIMIT = 31
_INVALID_SHEET = re.compile(r"[\[\]:*?/\\]")


@dataclass
class RunRecord:
    """One analysed dataset, ready to be written out."""
    sample: str
    measurement: Measurement
    result: AnalysisResult
    source: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    mapping: dict[str, str] = field(default_factory=dict)   # channel -> file column

    @property
    def title(self) -> str:
        return f"{self.sample} · {self.measurement.name}"


@dataclass
class ExcelReport:
    """Everything that goes into the workbook."""
    runs: list[RunRecord] = field(default_factory=list)
    project: str = "AeroLab Studio session"
    author: str = ""
    validation: list = field(default_factory=list)
    manual: list[dict[str, Any]] = field(default_factory=list)
    include_curves: bool = True
    include_charts: bool = True
    group_tables: bool = True       # runs of a "table" measurement share one sheet
    theme: str = "light"

    def add(self, record: RunRecord) -> None:
        self.runs.append(record)


# ---------------------------------------------------------------------------
def write_workbook(report: ExcelReport, path: str | Path) -> Path:
    """Write the report and return the path. Raises if xlsxwriter is missing."""
    import xlsxwriter

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(p), {"nan_inf_to_errors": True, "constant_memory": False})
    try:
        fmt = _formats(book, report.theme)
        _summary_sheet(book, fmt, report)
        if report.manual:
            _manual_sheet(book, fmt, report)
        if report.validation:
            _validation_sheet(book, fmt, report)

        used: set[str] = {"Summary", "Calculations", "Validation"}
        chart_targets: list[tuple[str, RunRecord, int, int, dict]] = []
        for group in _group_runs(report.runs, report.group_tables):
            if len(group) > 1 or group[0].measurement.kind == "table":
                # One row per sample beats one sheet per sample for a table measurement.
                name = _unique_sheet_name(group[0].measurement.name, used)
                _table_sheet(book, fmt, group, name)
                continue
            record = group[0]
            name = _unique_sheet_name(f"{record.sample} · {record.measurement.id}", used)
            rows = _run_sheet(book, fmt, record, name, report.include_curves)
            chart_targets.append((name, record, *rows))

        if report.include_charts and chart_targets:
            _charts_sheet(book, fmt, report, chart_targets)
        _provenance_sheet(book, fmt, report)
    finally:
        book.close()
    return p


# ---------------------------------------------------------------------------
# formats
# ---------------------------------------------------------------------------
def _formats(book, theme: str) -> dict:
    accent = S.THEMES.get(theme, S.THEMES["light"]).accent
    base = {"font_name": "Calibri", "font_size": 11}
    return {
        "title": book.add_format({**base, "font_size": 16, "bold": True, "font_color": "#1B1F24"}),
        "subtitle": book.add_format({**base, "font_size": 10, "font_color": "#6A7280", "italic": True}),
        "h2": book.add_format({**base, "font_size": 12, "bold": True, "font_color": accent,
                               "bottom": 1, "border_color": "#C9CED6"}),
        "header": book.add_format({**base, "bold": True, "font_color": "#FFFFFF", "bg_color": accent,
                                   "align": "left", "valign": "vcenter", "text_wrap": True,
                                   "border": 1, "border_color": "#FFFFFF"}),
        "cell": book.add_format({**base, "border": 1, "border_color": "#E3E6EA"}),
        "cell_alt": book.add_format({**base, "border": 1, "border_color": "#E3E6EA", "bg_color": "#F6F7F9"}),
        "num": book.add_format({**base, "num_format": "0.0000", "border": 1, "border_color": "#E3E6EA"}),
        "num_alt": book.add_format({**base, "num_format": "0.0000", "border": 1,
                                    "border_color": "#E3E6EA", "bg_color": "#F6F7F9"}),
        "sci": book.add_format({**base, "num_format": "0.000E+00", "border": 1, "border_color": "#E3E6EA"}),
        "data": book.add_format({**base, "num_format": "0.000000"}),
        "bold": book.add_format({**base, "bold": True}),
        "muted": book.add_format({**base, "font_color": "#6A7280"}),
        "wrap": book.add_format({**base, "text_wrap": True, "valign": "top"}),
        "ok": book.add_format({**base, "font_color": "#0B7A4B", "bold": True, "border": 1,
                               "border_color": "#E3E6EA"}),
        "bad": book.add_format({**base, "font_color": "#B3261E", "bold": True, "border": 1,
                                "border_color": "#E3E6EA"}),
        "note": book.add_format({**base, "font_color": "#8A6D00", "border": 1,
                                 "border_color": "#E3E6EA"}),
    }


def _num_fmt(fmt: dict, value: float, alt: bool) -> Any:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return fmt["cell_alt"] if alt else fmt["cell"]
    if value != 0 and (abs(value) >= 1e6 or abs(value) < 1e-3):
        return fmt["sci"]
    return fmt["num_alt"] if alt else fmt["num"]


def _safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "n/a"
    return value


# ---------------------------------------------------------------------------
# sheets
# ---------------------------------------------------------------------------
def _summary_sheet(book, fmt, report: ExcelReport) -> None:
    ws = book.add_worksheet("Summary")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 24)
    ws.set_column("B:B", 30)
    ws.set_column("C:C", 34)
    ws.set_column("D:D", 15)
    ws.set_column("E:E", 16)
    ws.set_column("F:F", 46)
    ws.freeze_panes(5, 0)

    ws.write(0, 0, report.project, fmt["title"])
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    who = f" · {report.author}" if report.author else ""
    ws.write(1, 0, f"AeroLab Studio · exported {stamp}{who}", fmt["subtitle"])
    ws.write(2, 0, f"{len(report.runs)} analysed dataset(s)", fmt["subtitle"])

    headers = ["Sample", "Measurement", "Quantity", "Value", "Unit", "Note"]
    for c, h in enumerate(headers):
        ws.write(4, c, h, fmt["header"])
    ws.autofilter(4, 0, 4, len(headers) - 1)

    row = 5
    for i, record in enumerate(report.runs):
        alt = i % 2 == 1
        cell = fmt["cell_alt"] if alt else fmt["cell"]
        for metric in record.result.metrics:
            ws.write(row, 0, record.sample, cell)
            ws.write(row, 1, record.measurement.name, cell)
            ws.write(row, 2, metric.name, cell)
            ws.write(row, 3, _safe(metric.value), _num_fmt(fmt, metric.value, alt))
            ws.write(row, 4, metric.unit or "-", cell)
            ws.write(row, 5, metric.note or "", cell)
            row += 1
    if row == 5:
        ws.write(5, 0, "No analyses in this session.", fmt["muted"])


def _manual_sheet(book, fmt, report: ExcelReport) -> None:
    """Equations evaluated by hand in the Calculator."""
    ws = book.add_worksheet("Calculations")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 34)
    ws.set_column("B:B", 46)
    ws.set_column("C:C", 16)
    ws.set_column("D:D", 14)
    ws.set_column("E:E", 44)
    ws.write(0, 0, "Manual calculations", fmt["title"])
    ws.write(1, 0, "Every equation evaluated in the Calculator, with its inputs.", fmt["subtitle"])
    ws.set_column("F:F", 14)
    for c, h in enumerate(["Equation", "Inputs", "Result", "Unit", "Reference", "± (1σ)"]):
        ws.write(3, c, h, fmt["header"])
    for i, entry in enumerate(report.manual):
        alt = i % 2 == 1
        cell = fmt["cell_alt"] if alt else fmt["cell"]
        r = 4 + i
        ws.write(r, 0, entry.get("name", ""), cell)
        ws.write(r, 1, entry.get("inputs", ""), cell)
        ws.write(r, 2, _safe(entry.get("value")), _num_fmt(fmt, entry.get("value", 0.0), alt))
        ws.write(r, 3, entry.get("unit", ""), cell)
        ws.write(r, 4, entry.get("reference", ""), cell)
        sigma = entry.get("uncertainty")
        if sigma is None:
            ws.write(r, 5, "—", cell)
        else:
            ws.write(r, 5, _safe(sigma), _num_fmt(fmt, sigma, alt))


def _validation_sheet(book, fmt, report: ExcelReport) -> None:
    """The equation library recomputing numbers printed in the papers."""
    ws = book.add_worksheet("Validation")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 36)
    ws.set_column("B:B", 13)
    ws.set_column("C:C", 13)
    ws.set_column("D:D", 11)
    ws.set_column("E:E", 12)
    ws.set_column("F:F", 40)
    ws.set_column("G:G", 60)
    ws.write(0, 0, "Self-validation against the source papers", fmt["title"])
    ws.write(1, 0, "Basis says what the reference is: 'paper' = printed in the paper, "
                   "'cross-check' = physics/textbook value, 'ours' = our recomputation (the paper "
                   "prints none, or prints a value we could not reproduce — shown under 'Paper prints'). "
                   "Rows marked 'documented' are inconsistencies in the papers themselves.",
             fmt["subtitle"])
    ws.set_column("H:I", 13)
    for c, h in enumerate(["Case", "Computed", "Reference", "Rel. error", "Status",
                           "Source", "Comment", "Basis", "Paper prints"]):
        ws.write(3, c, h, fmt["header"])
    for i, res in enumerate(report.validation):
        r = 4 + i
        alt = i % 2 == 1
        cell = fmt["cell_alt"] if alt else fmt["cell"]
        expect_match = getattr(res.case, "expect_match", True)
        ws.write(r, 0, res.case.name, cell)
        ws.write(r, 1, _safe(res.value), _num_fmt(fmt, res.value, alt))
        ws.write(r, 2, _safe(res.case.expected), _num_fmt(fmt, res.case.expected, alt))
        ws.write(r, 3, _safe(res.rel_error), fmt["sci"] if res.rel_error < 1e-3 else
                 (fmt["num_alt"] if alt else fmt["num"]))
        if not res.ok:
            ws.write(r, 4, "FAILED", fmt["bad"])
        elif expect_match:
            ws.write(r, 4, "reproduced", fmt["ok"])
        else:
            ws.write(r, 4, "documented", fmt["note"])
        ws.write(r, 5, res.case.source, cell)
        ws.write(r, 6, getattr(res.case, "comment", "") or "", cell)
        ws.write(r, 7, getattr(res.case, "basis", "paper"), cell)
        printed = getattr(res.case, "printed_value", res.case.expected)
        if printed is None:
            ws.write(r, 8, "—", cell)
        else:
            ws.write(r, 8, _safe(printed), _num_fmt(fmt, printed, alt))


def _run_sheet(book, fmt, record: RunRecord, name: str,
               include_curves: bool) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """Write one run.

    Returns (first data row, number of data rows, {curve: (x column, points)}) for the
    chart sheet. Curves longer than MAX_CHART_POINTS get an evenly thinned copy in extra
    columns for the chart, so the chart spans the whole curve instead of its first part.
    """
    ws = book.add_worksheet(name)
    ws.hide_gridlines(2)
    ws.set_column("A:A", 34)
    ws.set_column("B:B", 14)
    ws.set_column("C:C", 14)
    ws.set_column("D:D", 52)

    ws.write(0, 0, record.title, fmt["title"])
    subtitle = record.measurement.summary
    if record.source:
        subtitle += f"   ·   source: {Path(record.source).name}"
    ws.write(1, 0, subtitle, fmt["subtitle"])
    if record.measurement.reference:
        ws.write(2, 0, f"Method: {record.measurement.reference}", fmt["muted"])

    ws.write(4, 0, "Results", fmt["h2"])
    for c, h in enumerate(["Quantity", "Value", "Unit", "Note"]):
        ws.write(5, c, h, fmt["header"])
    row = 6
    for i, metric in enumerate(record.result.metrics):
        alt = i % 2 == 1
        cell = fmt["cell_alt"] if alt else fmt["cell"]
        ws.write(row, 0, metric.name, cell)
        ws.write(row, 1, _safe(metric.value), _num_fmt(fmt, metric.value, alt))
        ws.write(row, 2, metric.unit or "-", cell)
        ws.write(row, 3, metric.note or "", cell)
        row += 1

    if record.options:
        row += 1
        ws.write(row, 0, "Settings used", fmt["h2"])
        row += 1
        for key, value in record.options.items():
            ws.write(row, 0, str(key), fmt["cell"])
            ws.write(row, 1, str(value), fmt["cell"])
            row += 1

    if not include_curves or not record.result.curves:
        return row + 2, 0, {}

    # Curves start in column F so the results block stays readable next to them.
    start_col = 5
    ws.write(4, start_col, "Curves", fmt["h2"])
    header_row = 5
    col = start_col
    longest = 0
    chart_cols: dict[str, tuple[int, int]] = {}
    thinned: list[tuple[str, np.ndarray, np.ndarray]] = []
    for key, (x, y) in record.result.curves.items():
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        n = min(x.size, y.size)
        ws.set_column(col, col + 1, 13)
        ws.write(header_row, col, f"{key} · x", fmt["header"])
        ws.write(header_row, col + 1, f"{key} · y", fmt["header"])
        ws.write_column(header_row + 1, col, [_safe(v) for v in x[:n]], fmt["data"])
        ws.write_column(header_row + 1, col + 1, [_safe(v) for v in y[:n]], fmt["data"])
        if n > MAX_CHART_POINTS:
            idx = np.unique(np.linspace(0, n - 1, MAX_CHART_POINTS).round().astype(int))
            thinned.append((key, x[idx], y[idx]))
        else:
            chart_cols[key] = (col, n)
        longest = max(longest, n)
        col += 2
    for key, x, y in thinned:
        ws.set_column(col, col + 1, 13)
        ws.write(header_row, col, f"{key} · x (thinned for chart)", fmt["header"])
        ws.write(header_row, col + 1, f"{key} · y (thinned for chart)", fmt["header"])
        ws.write_column(header_row + 1, col, [_safe(v) for v in x], fmt["data"])
        ws.write_column(header_row + 1, col + 1, [_safe(v) for v in y], fmt["data"])
        chart_cols[key] = (col, int(x.size))
        col += 2
    ws.freeze_panes(header_row + 1, 0)
    return header_row + 1, longest, chart_cols


def _group_runs(runs: Sequence[RunRecord], group_tables: bool) -> list[list[RunRecord]]:
    """Collect consecutive runs of the same table measurement so they share a sheet."""
    groups: list[list[RunRecord]] = []
    for record in runs:
        collapsible = group_tables and record.measurement.kind == "table"
        if (collapsible and groups and groups[-1][0].measurement.id == record.measurement.id
                and groups[-1][0].measurement.kind == "table"):
            groups[-1].append(record)
        else:
            groups.append([record])
    return groups


def _table_sheet(book, fmt, group: Sequence[RunRecord], name: str) -> None:
    """A table measurement: samples down the rows, quantities across the columns."""
    ws = book.add_worksheet(name)
    ws.hide_gridlines(2)
    measurement = group[0].measurement
    ws.write(0, 0, measurement.name, fmt["title"])
    ws.write(1, 0, measurement.summary, fmt["subtitle"])
    if measurement.reference:
        ws.write(2, 0, f"Method: {measurement.reference}", fmt["muted"])

    quantities: list[str] = []
    for record in group:
        for metric in record.result.metrics:
            if metric.name not in quantities:
                quantities.append(metric.name)
    units = {m.name: m.unit for record in group for m in record.result.metrics}

    ws.set_column(0, 0, 26)
    ws.set_column(1, len(quantities), 17)
    ws.write(4, 0, "Sample", fmt["header"])
    for c, q in enumerate(quantities, start=1):
        unit = units.get(q) or ""
        ws.write(4, c, f"{q}\n({unit})" if unit and unit != "-" else q, fmt["header"])
    ws.set_row(4, 34)
    ws.freeze_panes(5, 1)
    ws.autofilter(4, 0, 4, len(quantities))

    for r, record in enumerate(group):
        alt = r % 2 == 1
        cell = fmt["cell_alt"] if alt else fmt["cell"]
        ws.write(5 + r, 0, record.sample, cell)
        values = record.result.as_dict()
        for c, q in enumerate(quantities, start=1):
            value = values.get(q)
            if value is None:
                ws.write(5 + r, c, "", cell)
            else:
                ws.write(5 + r, c, _safe(value), _num_fmt(fmt, value, alt))


def _charts_sheet(book, fmt, report: ExcelReport, targets) -> None:
    """Native Excel charts, one per plot defined by each measurement."""
    ws = book.add_worksheet("Charts")
    ws.hide_gridlines(2)
    ws.write(0, 0, "Charts", fmt["title"])
    ws.write(1, 0, "Live Excel charts linked to the per-sample sheets — edit them like any "
                   "other chart. Origin exports carry the full publication styling.",
             fmt["subtitle"])

    anchor_row = 3
    for sheet_name, record, first_row, n_rows, curve_cols in targets:
        if not n_rows:
            continue
        for plot in record.measurement.plots:
            chart = _build_chart(book, sheet_name, record, plot, curve_cols, first_row,
                                 n_rows, report.theme)
            if chart is None:
                continue
            ws.insert_chart(anchor_row, 0, chart, {"x_offset": 8, "y_offset": 8})
            anchor_row += 17
    if anchor_row == 3:
        ws.write(3, 0, "No chartable curves in this session.", fmt["muted"])


def _build_chart(book, sheet_name: str, record: RunRecord, plot: Plot,
                 curve_cols: dict[str, int], first_row: int, n_rows: int, theme: str):
    keys: list[tuple[str, str, str]] = []
    for series in plot.series:
        if series.curve == "*":
            keys += [(k, k, series.role) for k in record.result.curves]
        elif series.curve in record.result.curves:
            keys.append((series.curve, series.label, series.role))
    keys = [k for k in keys if k[0] in curve_cols]
    if not keys:
        return None
    del n_rows                                       # each curve carries its own length

    chart = book.add_chart({"type": "scatter", "subtype": "straight_with_markers"})
    data_index = 0
    for key, label, role in keys:
        col, n = curve_cols[key]
        if n < 2:
            continue
        last = first_row + n - 1
        st = S.style_for(data_index, role, label=label, theme=theme,
                         style_hint=plot.series[0].style if plot.series else "scatter")
        if role != "fit":
            data_index += 1
        series: dict[str, Any] = {
            "name": label,
            "categories": [sheet_name, first_row, col, last, col],
            "values": [sheet_name, first_row, col + 1, last, col + 1],
            "line": ({"none": True} if st.line_width <= 0 else
                     {"color": st.colour, "width": max(st.line_width, 0.75),
                      "dash_type": _excel_dash(st.line_style)}),
        }
        if st.symbol == "none":
            series["marker"] = {"type": "none"}
        else:
            series["marker"] = {
                "type": _excel_marker(st.symbol),
                "size": max(3, int(round(st.symbol_size))),
                "border": {"color": st.colour},
                "fill": {"color": st.colour} if st.filled else {"none": True},
            }
        chart.add_series(series)

    chart.set_title({"name": f"{record.sample} — {plot.title}",
                     "name_font": {"size": 12, "bold": True}})
    chart.set_x_axis({"name": plot.x_axis, "log_base": 10 if plot.xscale == "log" else None,
                      "major_gridlines": {"visible": False}})
    chart.set_y_axis({"name": plot.y_axis, "log_base": 10 if plot.yscale == "log" else None,
                      "major_gridlines": {"visible": True,
                                          "line": {"color": "#E3E6EA", "width": 0.75}}})
    chart.set_legend({"position": "bottom" if len(keys) > 3 else "right",
                      "font": {"size": 9}})
    chart.set_size({"width": 660, "height": 330})
    chart.set_chartarea({"border": {"color": "#D8DCE1"}, "fill": {"color": "#FFFFFF"}})
    chart.set_plotarea({"fill": {"color": "#FFFFFF"}})
    return chart


_EXCEL_MARKERS = {"circle": "circle", "square": "square", "triangle_up": "triangle",
                  "triangle_down": "triangle", "diamond": "diamond", "hexagon": "diamond",
                  "star": "star", "cross": "x", "plus": "plus"}
_EXCEL_DASH = {"solid": "solid", "dash": "dash", "dot": "round_dot",
               "dashdot": "dash_dot", "longdash": "long_dash"}


def _excel_marker(symbol: str) -> str:
    return _EXCEL_MARKERS.get(symbol, "circle")


def _excel_dash(line_style: str) -> str:
    return _EXCEL_DASH.get(line_style, "solid")


def _provenance_sheet(book, fmt, report: ExcelReport) -> None:
    """Enough detail to retrace any number in this workbook."""
    ws = book.add_worksheet("Provenance")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 28)
    ws.set_column("B:B", 90)
    ws.write(0, 0, "Provenance", fmt["title"])
    ws.write(1, 0, "What produced these numbers, and from what.", fmt["subtitle"])

    rows: list[tuple[str, str]] = [
        ("Exported", datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")),
        ("Project", report.project),
        ("Author", report.author or "-"),
        ("Application", f"AeroLab Studio {_app_version()}"),
        ("Python", sys.version.split()[0]),
        ("Platform", f"{platform.system()} {platform.release()}"),
        ("NumPy", np.__version__),
    ]
    for module in ("scipy", "matplotlib", "xlsxwriter", "originpro"):
        try:
            rows.append((module, __import__(module).__version__))
        except Exception:                                   # noqa: BLE001 - optional
            rows.append((module, "not installed" if module == "originpro" else "unknown"))

    r = 3
    for label, value in rows:
        ws.write(r, 0, label, fmt["bold"])
        ws.write(r, 1, str(value), fmt["cell"])
        r += 1

    r += 1
    ws.write(r, 0, "Datasets", fmt["h2"])
    r += 1
    for c, h in enumerate(["Sample", "Measurement / source / settings"]):
        ws.write(r, c, h, fmt["header"])
    r += 1
    for record in report.runs:
        opts = ", ".join(f"{k}={v}" for k, v in record.options.items()) or "defaults"
        lines = [record.measurement.name, f"Source: {record.source or 'in-app data'}"]
        digest = _sha256(record.source)
        if digest:
            lines.append(f"SHA-256 of source file: {digest}")
        if record.mapping:
            lines.append("Columns: " + ", ".join(f"{k} ← {v}" for k, v in record.mapping.items()))
        lines.append(f"Settings: {opts}")
        for note in record.result.meta.get("import_notes", []):
            lines.append(f"Import: {note}")
        ws.write(r, 0, record.sample, fmt["cell"])
        ws.write(r, 1, "\n".join(lines), fmt["wrap"])
        ws.set_row(r, 15 * len(lines))
        r += 1


def _app_version() -> str:
    try:
        from .. import __version__
        return __version__
    except Exception:                                        # noqa: BLE001
        return "unknown version"


def _sha256(path: str) -> str:
    """Hash of the source file, so a reader can tell whether it changed since export."""
    import hashlib
    try:
        p = Path(path)
        if not path or not p.is_file():
            return ""
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
def _unique_sheet_name(title: str, used: set[str]) -> str:
    base = _INVALID_SHEET.sub("-", title).strip() or "Sheet"
    base = base[:SHEET_NAME_LIMIT]
    name, n = base, 2
    while name.lower() in {u.lower() for u in used}:
        suffix = f" ({n})"
        name = base[:SHEET_NAME_LIMIT - len(suffix)] + suffix
        n += 1
    used.add(name)
    return name
