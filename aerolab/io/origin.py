"""Send results to OriginLab, styled the way a journal wants them.

Two routes, same styling, chosen automatically:

1. **Live automation** (`OriginBridge`) — drives an installed Origin through the
   `originpro` COM bridge: builds a workbook per dataset with proper Long Names, Units
   and Comments, plots every graph the measurement defines, applies the publication
   palette and symbol set, then saves a `.opju` project and exports images.

2. **Script package** (`write_script_package`) — when Origin is not on this machine,
   writes Origin-ready CSVs plus a LabTalk `.ogs` script that rebuilds exactly the same
   workbooks and graphs. Copy the folder to a machine with Origin, run one command, and
   the project is there.

Both read their colours and symbols from `aerolab.viz.style`, so an Origin figure matches
what the app showed on screen.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from ..core.curves import AnalysisResult
from ..core.measurements import Measurement, Plot
from ..viz import style as S

__all__ = [
    "OriginExportItem", "OriginResult", "OriginBridge", "origin_available",
    "write_script_package", "export_to_origin", "ORIGIN_SCALE",
]

ORIGIN_SCALE = {"linear": 1, "log": 2}
LINE_WIDTH_UNITS = 500          # LabTalk `set -w` counts in 1/500 pt
SYMBOL_SIZE_UNITS = 1.0
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")


@dataclass
class OriginExportItem:
    """One dataset heading for Origin."""
    sample: str
    measurement: Measurement
    result: AnalysisResult
    source: str = ""
    uid: str = ""                 # set by _assign_ids so two items never share a file name

    @property
    def book_name(self) -> str:
        return _short(f"{self.sample} {self.measurement.id}", 30)

    @property
    def safe_id(self) -> str:
        return self.uid or _SAFE_NAME.sub("_", f"{self.sample}_{self.measurement.id}").strip("_")[:28]


def _assign_ids(items: Sequence[OriginExportItem]) -> None:
    """Unique ASCII ids. Without this, two runs of one sample (or two long names that
    agree in their first 28 characters) overwrite each other's CSV, book and images."""
    used: set[str] = set()
    for item in items:
        base = _SAFE_NAME.sub("_", f"{item.sample}_{item.measurement.id}").strip("_")[:20] or "item"
        uid, n = base, 2
        while uid.lower() in used:
            uid = f"{base}_{n}"
            n += 1
        used.add(uid.lower())
        item.uid = uid


@dataclass
class OriginResult:
    """What an export produced."""
    mode: str                                   # "live" | "script"
    project: Path | None = None
    images: list[Path] = field(default_factory=list)
    folder: Path | None = None
    books: int = 0
    graphs: int = 0
    messages: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.mode == "live":
            return (f"{self.books} workbook(s) and {self.graphs} graph(s) in Origin"
                    + (f", saved to {self.project.name}" if self.project else "")
                    + (f", {len(self.images)} image(s) exported" if self.images else ""))
        return (f"Origin script package written to {self.folder} "
                f"({self.books} dataset(s), {self.graphs} graph(s)) — "
                f"run AeroLab_build.ogs in Origin")


# ---------------------------------------------------------------------------
# availability
# ---------------------------------------------------------------------------
def origin_available() -> tuple[bool, str]:
    """(usable, why-not). Checks both the Python package and the COM registration."""
    try:
        import originpro                                      # noqa: F401
    except ImportError:
        return False, "The 'originpro' package is not installed (pip install originpro)."
    try:
        import win32com.client                                # noqa: F401
    except ImportError:
        return False, "pywin32 is not installed, so Origin's automation server cannot be reached."
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Origin.ApplicationSI"))
    except OSError:
        return False, "OriginLab is not installed, or its automation server is not registered."
    return True, "Origin automation is available."


# ---------------------------------------------------------------------------
# live automation
# ---------------------------------------------------------------------------
class OriginBridge:
    """Context manager around an Origin session.

    Origin is slow to start (about ten seconds) and must be shut down cleanly, so it is
    opened once per export and always closed, even when something goes wrong.
    """

    def __init__(self, visible: bool = False, keep_open: bool = False) -> None:
        self.visible = visible
        self.keep_open = keep_open
        self.op: Any = None
        self._started = False

    def __enter__(self) -> "OriginBridge":
        ok, why = origin_available()
        if not ok:
            raise RuntimeError(why)
        import originpro as op
        self.op = op
        op.set_show(self.visible)
        self._started = True
        return self

    def __exit__(self, *exc_info) -> None:
        if self._started and self.op is not None and not self.keep_open:
            try:
                self.op.exit()
            except Exception:                                  # noqa: BLE001 - shutdown is best-effort
                pass
        self._started = False

    # -- building ------------------------------------------------------------
    def build(self, items: Sequence[OriginExportItem], *, palette_name: str | None = None,
              theme: str = "light") -> tuple[int, int, list]:
        """Create a workbook and its graphs for every item. Returns (books, graphs, pages)."""
        books = graphs = 0
        pages = []
        for item in items:
            wks = self._build_workbook(item)
            books += 1
            for plot in item.measurement.plots:
                page = self._build_graph(item, plot, wks, palette_name, theme)
                if page is not None:
                    pages.append((item, plot, page))
                    graphs += 1
        return books, graphs, pages

    def _build_workbook(self, item: OriginExportItem):
        """A workbook whose columns carry Long Name, Units and Comments — as Origin expects."""
        op = self.op
        book = op.new_book("w", lname=item.book_name)
        wks = book[0]
        wks.lname = _short(item.measurement.name, 30)

        labels = _curve_labels(item.measurement, item.result)
        long_names: list[str] = []
        units: list[str] = []
        comments: list[str] = []
        col = 0
        for key, (x, y) in item.result.curves.items():
            x = np.asarray(x, dtype=float).ravel()
            y = np.asarray(y, dtype=float).ravel()
            n = min(x.size, y.size)
            if n == 0:
                continue
            plot = _plot_for_curve(item.measurement, key)
            x_label, x_unit = (plot.x_label, plot.x_unit) if plot else ("X", "")
            y_label, y_unit = (plot.y_label, plot.y_unit) if plot else ("Y", "")
            wks.from_list(col, [float(v) for v in x[:n]])
            wks.from_list(col + 1, [float(v) for v in y[:n]])
            long_names += [x_label, y_label]
            units += [x_unit, y_unit]
            # Origin's default legend entry is the Y column's Comments, so the display
            # label goes there rather than the internal curve key.
            comments += [labels.get(key, key), labels.get(key, key)]
            col += 2

        if long_names:
            wks.set_labels(long_names, "L")
            wks.set_labels(units, "U")
            wks.set_labels(comments, "C")
        # X columns are designated X, the ones after them Y, so plots pair up correctly.
        for i in range(0, col, 2):
            wks.cols_axis("xy", i, 2)

        note = f"{item.measurement.name} — {item.sample}"
        if item.source:
            note += f"\nSource: {item.source}"
        if item.measurement.reference:
            note += f"\nMethod: {item.measurement.reference}"
        metrics = "\n".join(f"{m.name} = {m.value:.6g} {m.unit}".strip()
                            for m in item.result.metrics
                            if isinstance(m.value, float) and math.isfinite(m.value))
        book.comments = f"{note}\n\n{metrics}"
        return wks

    def _build_graph(self, item: OriginExportItem, plot: Plot, wks, palette_name, theme):
        op = self.op
        curve_cols = {key: 2 * i for i, key in enumerate(item.result.curves)}
        series = _expand_series(plot, item.result)
        series = [s for s in series if s[0] in curve_cols]
        if not series:
            return None

        page = op.new_graph(lname=_short(f"{item.sample} {plot.title}", 30),
                            template="scatter")
        layer = page[0]

        data_index = 0
        data_slots: dict[str, int] = {}
        last_data: int | None = None
        for key, label, role in series:
            col = curve_cols[key]
            hint = _hint_for(plot, key)
            if role == "fit":
                parent = data_slots.get(_stem(key))
                if parent is None and len(data_slots) == 1:
                    parent = last_data
                st = S.style_for(data_index, "fit", palette_name=palette_name, label=label,
                                 parent=parent, theme=theme, style_hint=hint)
            else:
                st = S.style_for(data_index, role, palette_name=palette_name, label=label,
                                 theme=theme, style_hint=hint)
                data_slots[_stem(key)] = data_index
                last_data = data_index
                data_index += 1
            dp = layer.add_plot(wks, coly=col + 1, colx=col, type=_origin_plot_type(st))
            if dp is not None:
                _style_plot(dp, st)

        layer.axis("x").title = plot.x_axis
        layer.axis("y").title = plot.y_axis
        if plot.xscale == "log" and _all_positive(item.result, [s[0] for s in series], axis=0):
            layer.axis("x").scale = "log10"
        if plot.yscale == "log" and _all_positive(item.result, [s[0] for s in series], axis=1):
            layer.axis("y").scale = "log10"
        layer.rescale()
        _add_legend(layer, plot.title)
        return page

    # -- output --------------------------------------------------------------
    def save_project(self, path: str | Path) -> Path:
        p = Path(path).with_suffix(".opju")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.op.save(str(p))
        return p

    def export_images(self, pages, folder: str | Path, *, fmt: str = "png",
                      width: int = 1800) -> list[Path]:
        out: list[Path] = []
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        for item, plot, page in pages:
            dest = target / f"{item.safe_id}_{plot.id}.{fmt}"
            try:
                page.save_fig(str(dest), type=fmt, replace=True, width=width)
                if dest.exists():
                    out.append(dest)
            except Exception:                                  # noqa: BLE001 - reported to the user
                continue
        return out


def _style_plot(dp, st: S.SeriesStyle) -> None:
    """Apply one series style to an Origin data plot.

    Symbol shape, size and interior go through originpro's documented properties, which
    set `plotN.symbol.*` directly; only line width and style need LabTalk.
    """
    try:
        dp.color = st.colour
    except Exception:                                          # noqa: BLE001
        pass
    commands: list[str] = []
    try:
        if st.symbol == "none" or st.symbol_size <= 0:
            commands.append("-k 0")                            # no symbol at all
        else:
            dp.symbol_kind = st.origin_symbol
            dp.symbol_size = float(st.symbol_size)
            dp.symbol_interior = st.origin_symbol_interior     # 0 = filled, 1 = open
            # On a line+symbol plot `dp.color` only reaches the line, leaving the symbol
            # at Origin's default black, so the symbol colour is set explicitly here.
            commands.append(f"-c {_lt_color(st)}")
    except Exception:                                          # noqa: BLE001
        pass
    if st.line_width > 0:
        commands.append(f"-w {int(round(st.line_width * LINE_WIDTH_UNITS))}")
        commands.append(f"-d {st.origin_line_style}")
        commands.append(f"-cl {_lt_color(st)}")
    if commands:
        try:
            dp.set_cmd(*commands)
        except Exception:                                      # noqa: BLE001 - styling is best-effort
            pass


def _lt_color(st: S.SeriesStyle) -> str:
    """LabTalk colour literal. The r,g,b form parses reliably; the #hex form does not."""
    r, g, b = st.rgb
    return f"color({r},{g},{b})"


def _add_legend(layer, title: str) -> None:
    """Rebuild the legend.

    Plain `legendupdate` picks up each Y column's Comments, which is where the series
    labels were written. Passing mode/update arguments switches Origin to a different
    text form and prints raw column ranges instead, so they are deliberately omitted.
    """
    try:
        layer.lt_exec("legendupdate;")
    except Exception:                                          # noqa: BLE001
        pass


def _origin_plot_type(st: S.SeriesStyle) -> str:
    if st.symbol == "none" or st.symbol_size <= 0:
        return "l"                                             # line
    return "y" if st.line_width > 0 else "s"                   # line+symbol, or scatter


# ---------------------------------------------------------------------------
# script package (no Origin on this machine)
# ---------------------------------------------------------------------------
def write_script_package(items: Sequence[OriginExportItem], folder: str | Path, *,
                         palette_name: str | None = None, theme: str = "light",
                         project_name: str = "AeroLab") -> OriginResult:
    """Origin-ready CSVs plus a LabTalk script that rebuilds the whole project."""
    out = Path(folder)
    (out / "data").mkdir(parents=True, exist_ok=True)

    # No [Main] section: Origin executes a section-less .ogs straight through when it is
    # opened or passed to run.file, which is one less thing for the reader to get right.
    lines: list[str] = [
        "// ---------------------------------------------------------------",
        f"// {project_name} — generated by AeroLab Studio",
        "//",
        "// In Origin:  File > Open, choose this file (file type: LabTalk Script *.ogs)",
        '//        or:  run.file("<full path to this file>");   in the Script Window',
        "//",
        "// It imports every CSV in .\\data and rebuilds the styled graphs.",
        "// ---------------------------------------------------------------",
        "string gpath$ = %X;",          # %X = the folder this script lives in
        "if (gpath$ == \"\") { type \"AeroLab: set gpath$ to this folder, then re-run.\"; }",
        "",
    ]
    graphs = 0
    _assign_ids(items)
    for item in items:
        csv_path = out / "data" / f"{item.safe_id}.csv"
        _write_origin_csv(item, csv_path)
        lines += _labtalk_for_item(item, csv_path.name, palette_name, theme)
        graphs += len([p for p in item.measurement.plots
                       if _expand_series(p, item.result)])

    lines += ["", f'save -i "%(gpath$){project_name}.opju";',
              f'type "AeroLab: {len(items)} workbook(s), {graphs} graph(s) built.";', ""]
    script = out / "AeroLab_build.ogs"
    script.write_text("\n".join(lines), encoding="utf-8")
    _write_package_readme(out, items, script, project_name)
    return OriginResult(mode="script", folder=out, books=len(items), graphs=graphs,
                        messages=[f"Run {script.name} in Origin to rebuild the project."])


def _write_origin_csv(item: OriginExportItem, path: Path) -> None:
    """Origin's own import layout: Long Name, Units, Comments, then the numbers."""
    labels = _curve_labels(item.measurement, item.result)
    columns: list[tuple[str, str, str, np.ndarray]] = []
    for key, (x, y) in item.result.curves.items():
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        n = min(x.size, y.size)
        if n == 0:
            continue
        plot = _plot_for_curve(item.measurement, key)
        xl, xu = (plot.x_label, plot.x_unit) if plot else ("X", "")
        yl, yu = (plot.y_label, plot.y_unit) if plot else ("Y", "")
        label = labels.get(key, key)
        columns.append((xl, xu, label, x[:n]))
        columns.append((yl, yu, label, y[:n]))
    if not columns:
        path.write_text("Long Name\nUnits\nComments\n", encoding="utf-8")
        return

    height = max(c[3].size for c in columns)
    rows = [
        ",".join(_csv(c[0]) for c in columns),
        ",".join(_csv(c[1]) for c in columns),
        ",".join(_csv(c[2]) for c in columns),
    ]
    for r in range(height):
        rows.append(",".join("" if r >= c[3].size or not math.isfinite(c[3][r])
                             else f"{c[3][r]:.10g}" for c in columns))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _labtalk_for_item(item: OriginExportItem, csv_name: str, palette_name, theme) -> list[str]:
    # Origin strips spaces and punctuation when it derives a book's short name from its
    # long name ("My Book-4" becomes MyBook4), so the short name is captured from
    # `result:=` and every range is written against that. Writing the long name into a
    # range silently matches nothing and the script quietly builds empty graphs.
    book = f"bk_{item.safe_id[:24]}" if item.safe_id else "bk_data"
    lines = [
        f"// ---- {item.sample} · {item.measurement.name}",
        f'newbook name:="{_lt(item.book_name)}" sheet:=1 option:=lsname;',
        # Bare impasc, deliberately. The CSV is written in Origin's own layout (row 1 Long
        # Name, row 2 Units, row 3 Comments) and Origin's auto-detection reads it correctly.
        # Passing options.names.* explicitly makes the import return zero rows.
        f'impasc fname:="%(gpath$)data\\{csv_name}";',
        # The short name is read *after* the import: a bare impasc renames the book after
        # the file, so a name captured from newbook would already be stale. The import also
        # overwrites the long name with the file path, so put the readable one back.
        f"string {book}$ = %H;",
        f'page.longname$ = "{_lt(item.book_name)}";',
    ]
    curve_cols = {key: 2 * i for i, key in enumerate(item.result.curves)}
    for i in range(0, 2 * len(curve_cols), 2):
        lines.append(f"wks.col{i + 1}.type = 4;")              # X
        lines.append(f"wks.col{i + 2}.type = 1;")              # Y

    for plot in item.measurement.plots:
        series = [s for s in _expand_series(plot, item.result) if s[0] in curve_cols]
        if not series:
            continue
        lines.append("win -t plot;")
        lines.append(f"string {book}_gr$ = %H;")
        data_index = 0
        plot_index = 0
        data_slots: dict[str, int] = {}
        last_data: int | None = None
        for key, label, role in series:
            col = curve_cols[key]
            hint = _hint_for(plot, key)
            if role == "fit":
                parent = data_slots.get(_stem(key))
                if parent is None and len(data_slots) == 1:
                    parent = last_data
                st = S.style_for(data_index, "fit", palette_name=palette_name, label=label,
                                 parent=parent, theme=theme, style_hint=hint)
            else:
                st = S.style_for(data_index, role, palette_name=palette_name, label=label,
                                 theme=theme, style_hint=hint)
                data_slots[_stem(key)] = data_index
                last_data = data_index
                data_index += 1
            lines.append(f"plotxy iy:=[%({book}$)]1!({col + 1},{col + 2}) "
                         f"plot:={_labtalk_plot_type(st)} ogl:=<active>;")
            # `set %C` only ever reaches the first plot in the layer, so each plot is
            # addressed explicitly by its index — [Graph]layer!plot — the way originpro
            # does internally. Without this every trace after the first keeps Origin's
            # default grey.
            plot_index += 1
            lines.append(f"range rr{plot_index} = [%({book}_gr$)]1!{plot_index};")
            lines += [f"set rr{plot_index} {cmd};" for cmd in _labtalk_style_cmds(st)]
        lines.append(f'win -r %H "{_lt(_ascii_name(item.sample + " " + plot.id, 30))}";')
        lines.append(f'label -xb "{_lt(plot.x_axis)}";')
        lines.append(f'label -yl "{_lt(plot.y_axis)}";')
        if plot.xscale == "log" and _all_positive(item.result, [s[0] for s in series], 0):
            lines.append("layer.x.type = 2;")
        if plot.yscale == "log" and _all_positive(item.result, [s[0] for s in series], 1):
            lines.append("layer.y.type = 2;")
        lines.append("rescale;")
        lines.append("legendupdate;")
        lines.append("")
    return lines


def _ascii_name(text: str, limit: int) -> str:
    """A window name Origin will accept: ASCII letters, digits and underscores only."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")
    return (cleaned[:limit] or "AeroLab")


def _labtalk_style_cmds(st: S.SeriesStyle) -> list[str]:
    # `-c` sets the data plot's own colour, which is what a line-only plot reports and what
    # the legend swatch uses; `-cl` only reaches the line segment. Both are sent, so a fit
    # drawn without symbols still comes out in its parent series' colour.
    cmds: list[str] = [f"-c {_lt_color(st)}"]
    if st.symbol == "none" or st.symbol_size <= 0:
        cmds.append("-k 0")
    else:
        cmds += [f"-k {st.origin_symbol}",
                 f"-z {max(1, int(round(st.symbol_size)))}",
                 f"-kf {st.origin_symbol_interior}"]   # 0 = filled, 1 = open
    if st.line_width > 0:
        cmds += [f"-w {int(round(st.line_width * LINE_WIDTH_UNITS))}",
                 f"-d {st.origin_line_style}",
                 f"-cl {_lt_color(st)}"]
    return cmds


def _labtalk_plot_type(st: S.SeriesStyle) -> int:
    if st.symbol == "none" or st.symbol_size <= 0:
        return 200                                             # line
    return 201 if st.line_width > 0 else 202                   # line+symbol / scatter


def _write_package_readme(folder: Path, items, script: Path, project_name: str) -> None:
    lines = [
        f"{project_name} — Origin export package",
        "=" * 46, "",
        "This folder was written by AeroLab Studio because OriginLab was not available",
        "on the machine that ran the analysis. Everything needed to rebuild the project",
        "in Origin is here.",
        "",
        "To rebuild:",
        "  1. Copy this whole folder to a machine with OriginLab.",
        "  2. Start Origin.",
        f"  3. File > Open, choose {script.name} (set the file type to LabTalk Script *.ogs).",
        "     Or type this in Origin's Script Window:",
        f"         run.file(\"{script.name}\");",
        f"  4. Origin builds one workbook per dataset, plots every graph with the same",
        f"     colours and symbols the app used, and saves {project_name}.opju next to the script.",
        "",
        "The CSVs in .\\data are Origin-ready on their own: row 1 is the Long Name,",
        "row 2 the Units and row 3 the Comments, so File > Import > Single ASCII works",
        "directly if you would rather do it by hand.",
        "",
        "Datasets in this package:",
    ]
    for item in items:
        lines.append(f"  · {item.sample:<24} {item.measurement.name} "
                     f"({len(item.measurement.plots)} graph(s))")
    (folder / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# one-call entry point
# ---------------------------------------------------------------------------
def export_to_origin(items: Sequence[OriginExportItem], destination: str | Path, *,
                     palette_name: str | None = None, theme: str = "light",
                     save_images: bool = True, visible: bool = False,
                     keep_open: bool = False, force_script: bool = False) -> OriginResult:
    """Export to Origin if it is here; otherwise write the script package.

    `destination` is a folder. A live export puts `AeroLab.opju` and any images in it;
    a script export fills it with CSVs and the .ogs script.
    """
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    _assign_ids(items)
    if not items:
        return OriginResult(mode="script", folder=dest, messages=["Nothing to export."])

    ok, why = origin_available()
    if force_script or not ok:
        result = write_script_package(items, dest, palette_name=palette_name, theme=theme)
        if not ok:
            result.messages.insert(0, why)
        return result

    with OriginBridge(visible=visible, keep_open=keep_open) as bridge:
        books, graphs, pages = bridge.build(items, palette_name=palette_name, theme=theme)
        project = bridge.save_project(dest / "AeroLab.opju")
        images = bridge.export_images(pages, dest / "figures") if save_images else []
    return OriginResult(mode="live", project=project, images=images, folder=dest,
                        books=books, graphs=graphs)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_ROLE_WORDS = {"fit", "data", "measured", "curve", "points", "plot", "branch"}


def _stem(curve_key: str) -> str:
    words = [w for w in curve_key.lower().replace("-", " ").split() if w not in _ROLE_WORDS]
    return " ".join(words) or curve_key.lower()


def _curve_labels(measurement: Measurement, result: AnalysisResult) -> dict[str, str]:
    """Display label for every curve, gathered from the plots that use it."""
    labels: dict[str, str] = {}
    for plot in measurement.plots:
        for key, label, _role in _expand_series(plot, result):
            labels.setdefault(key, label)
    return labels


def _expand_series(plot: Plot, result: AnalysisResult) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for series in plot.series:
        if series.curve == "*":
            for i, key in enumerate(result.curves, start=1):
                out.append((key, key if series.label in ("", "Cycle") else
                            f"{series.label} {i}", series.role))
        elif series.curve in result.curves:
            out.append((series.curve, series.label, series.role))
    return out


def _hint_for(plot: Plot, key: str) -> str:
    for s in plot.series:
        if s.curve == key:
            return s.style
    return plot.series[0].style if plot.series else "scatter"


def _plot_for_curve(measurement: Measurement, key: str) -> Plot | None:
    for plot in measurement.plots:
        for series in plot.series:
            if series.curve in (key, "*"):
                return plot
    return measurement.plots[0] if measurement.plots else None


def _all_positive(result: AnalysisResult, keys: Iterable[str], axis: int) -> bool:
    for key in keys:
        pair = result.curves.get(key)
        if not pair:
            continue
        values = np.asarray(pair[axis], dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size and finite.min() <= 0:
            return False
    return True


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _lt(text: str) -> str:
    """Escape a string for a LabTalk literal."""
    return str(text).replace('"', "'").replace("%", "%%").replace("\n", " ")


def _csv(text: str) -> str:
    text = str(text or "")
    return f'"{text}"' if any(c in text for c in ',"\n') else text
