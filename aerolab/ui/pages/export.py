"""Export page: Excel, Origin and image sets.

Origin can take ten to twenty seconds to start, so the export runs on a worker thread and
the window stays alive. If Origin is not installed the same button writes a LabTalk
package instead — the work is not lost, it just happens on another machine.
"""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from ...core import validation as V
from ...io import excel as X, origin as O
from ...viz import figures as F
from ..widgets import BusyBar, Card, EmptyState, Pill, scrollable
from .base import Page

__all__ = ["ExportPage"]


class _OriginWorker(QObject):
    """Runs the Origin export off the UI thread."""
    finished = Signal(object, str)          # OriginResult | None, error text

    def __init__(self, items, folder, palette, theme, save_images, visible, keep_open, force):
        super().__init__()
        self._args = (items, folder, palette, theme, save_images, visible, keep_open, force)

    def run(self) -> None:
        items, folder, palette, theme, save_images, visible, keep_open, force = self._args
        try:
            result = O.export_to_origin(items, folder, palette_name=palette, theme=theme,
                                        save_images=save_images, visible=visible,
                                        keep_open=keep_open, force_script=force)
            self.finished.emit(result, "")
        except Exception as exc:                                # noqa: BLE001 - reported in the UI
            self.finished.emit(None, f"{exc}\n\n{traceback.format_exc(limit=3)}")


class ExportPage(Page):
    title = "Export"
    subtitle = "One Excel workbook, an Origin project, or a folder of figures."
    glyph = "↗"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        self._thread: QThread | None = None
        self._worker: _OriginWorker | None = None
        self._build()
        session.runs_changed.connect(self.refresh)
        session.manual_changed.connect(self.refresh)
        self.refresh()

    def _build(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        # -- what will be exported
        scope = Card("What will be exported")
        self.scope_label = QLabel()
        self.scope_label.setObjectName("Hint")
        self.scope_label.setWordWrap(True)
        scope.body.addWidget(self.scope_label)
        self.run_list = QListWidget()
        self.run_list.setMaximumHeight(150)
        scope.body.addWidget(self.run_list)
        row = QHBoxLayout()
        btn_all = QPushButton("Select all")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("Select none")
        btn_none.clicked.connect(lambda: self._set_all(False))
        row.addWidget(btn_all)
        row.addWidget(btn_none)
        row.addStretch(1)
        scope.body.addLayout(row)

        meta = QGridLayout()
        meta.setSpacing(8)
        meta.addWidget(QLabel("Project name"), 0, 0)
        self.project_edit = QLineEdit(self.session.project_name)
        meta.addWidget(self.project_edit, 0, 1)
        meta.addWidget(QLabel("Author"), 1, 0)
        self.author_edit = QLineEdit(self.session.author)
        self.author_edit.setPlaceholderText("appears on the Summary and Provenance sheets")
        meta.addWidget(self.author_edit, 1, 1)
        scope.body.addLayout(meta)
        layout.addWidget(scope)

        # -- Excel
        excel = Card("Excel workbook",
                     "Summary of every result, one sheet per dataset with its curves, "
                     "native Excel charts, the validation table and a provenance record.")
        opts = QHBoxLayout()
        self.chk_curves = QCheckBox("Include raw curves")
        self.chk_curves.setChecked(True)
        self.chk_charts = QCheckBox("Include native charts")
        self.chk_charts.setChecked(True)
        self.chk_validation = QCheckBox("Include validation sheet")
        self.chk_validation.setChecked(True)
        opts.addWidget(self.chk_curves)
        opts.addWidget(self.chk_charts)
        opts.addWidget(self.chk_validation)
        opts.addStretch(1)
        excel.body.addLayout(opts)
        btn_row = QHBoxLayout()
        self.btn_excel = QPushButton("Export to Excel…")
        self.btn_excel.setObjectName("Primary")
        self.btn_excel.clicked.connect(self.export_excel)
        btn_row.addWidget(self.btn_excel)
        btn_row.addStretch(1)
        excel.body.addLayout(btn_row)
        layout.addWidget(excel)

        # -- Origin
        origin = Card("OriginLab")
        self.origin_status = QLabel()
        self.origin_status.setObjectName("Hint")
        self.origin_status.setWordWrap(True)
        origin.body.addWidget(self.origin_status)
        oopts = QHBoxLayout()
        self.chk_images = QCheckBox("Export PNG of each graph")
        self.chk_images.setChecked(True)
        self.chk_visible = QCheckBox("Show Origin while it works")
        self.chk_visible.setChecked(bool(self.session.settings.get("origin_visible")))
        self.chk_keep = QCheckBox("Leave Origin open afterwards")
        self.chk_keep.setChecked(bool(self.session.settings.get("origin_keep_open")))
        oopts.addWidget(self.chk_images)
        oopts.addWidget(self.chk_visible)
        oopts.addWidget(self.chk_keep)
        oopts.addStretch(1)
        origin.body.addLayout(oopts)

        obtn = QHBoxLayout()
        self.btn_origin = QPushButton("Export to Origin…")
        self.btn_origin.setObjectName("Primary")
        self.btn_origin.clicked.connect(lambda: self.export_origin(force_script=False))
        self.btn_script = QPushButton("Write LabTalk package…")
        self.btn_script.setToolTip("Origin-ready CSVs plus a script that rebuilds the project "
                                   "on a machine that has Origin")
        self.btn_script.clicked.connect(lambda: self.export_origin(force_script=True))
        obtn.addWidget(self.btn_origin)
        obtn.addWidget(self.btn_script)
        obtn.addStretch(1)
        origin.body.addLayout(obtn)
        self.busy = BusyBar()
        origin.body.addWidget(self.busy)
        layout.addWidget(origin)

        # -- images
        images = Card("Figure set",
                      "Every graph of every selected run, rendered at publication resolution.")
        irow = QHBoxLayout()
        irow.addWidget(QLabel("Format"))
        self.img_format = QComboBox()
        self.img_format.addItems(["PNG", "PDF", "SVG", "TIFF", "EPS"])
        irow.addWidget(self.img_format)
        irow.addWidget(QLabel("Size"))
        self.img_size = QComboBox()
        self.img_size.addItems(["single_column", "double_column", "square", "presentation"])
        irow.addWidget(self.img_size)
        irow.addWidget(QLabel("Resolution"))
        self.img_dpi = QComboBox()
        self.img_dpi.addItems(["print", "screen", "poster"])
        irow.addWidget(self.img_dpi)
        irow.addStretch(1)
        images.body.addLayout(irow)
        ibtn = QHBoxLayout()
        self.btn_images = QPushButton("Export figures…")
        self.btn_images.clicked.connect(self.export_images)
        ibtn.addWidget(self.btn_images)
        ibtn.addStretch(1)
        images.body.addLayout(ibtn)
        layout.addWidget(images)
        layout.addStretch(1)

        self.content.addWidget(scrollable(host), 1)

    # -- state ---------------------------------------------------------------
    def refresh(self) -> None:
        counts = self.session.counts()
        self.scope_label.setText(
            f"{counts['runs']} analysed run(s), {counts['metrics']} result(s) and "
            f"{counts['manual']} kept calculation(s) in this session.")
        checked = {self.run_list.item(i).data(Qt.UserRole)
                   for i in range(self.run_list.count())
                   if self.run_list.item(i).checkState() == Qt.Checked}
        first_fill = self.run_list.count() == 0
        self.run_list.clear()
        for run in self.session.runs:
            item = QListWidgetItem(f"{run.sample}  ·  {run.measurement.name}")
            item.setData(Qt.UserRole, run.run_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if first_fill or run.run_id in checked
                               else Qt.Unchecked)
            self.run_list.addItem(item)

        ok, why = O.origin_available()
        self.origin_status.setText(
            "OriginLab is available on this machine — graphs will be built directly, with "
            "publication colours and symbols, and saved as a .opju project.\n" + why if ok
            else why + "\nUse “Write LabTalk package” to produce Origin-ready CSVs and a "
                       "script that rebuilds everything on a machine that has Origin.")
        self.btn_origin.setEnabled(bool(self.session.runs))
        self.btn_script.setEnabled(bool(self.session.runs))
        self.btn_excel.setEnabled(bool(self.session.runs or self.session.manual))
        self.btn_images.setEnabled(bool(self.session.runs))

    def _set_all(self, checked: bool) -> None:
        for i in range(self.run_list.count()):
            self.run_list.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _selected_runs(self) -> list:
        ids = {self.run_list.item(i).data(Qt.UserRole)
               for i in range(self.run_list.count())
               if self.run_list.item(i).checkState() == Qt.Checked}
        return [r for r in self.session.runs if r.run_id in ids]

    def _remember(self, path: str) -> None:
        self.session.settings["last_export_dir"] = str(Path(path).parent)
        self.session.set_setting("author", self.author_edit.text().strip())
        self.session.project_name = self.project_edit.text().strip() or "AeroLab session"
        self.session.save_settings()

    # -- Excel ---------------------------------------------------------------
    def export_excel(self) -> None:
        runs = self._selected_runs()
        if not runs and not self.session.manual:
            self.session.status.emit("Nothing selected to export.", "warning")
            return
        start = self.session.settings.get("last_export_dir", str(Path.home()))
        name = (self.project_edit.text().strip() or "AeroLab_results").replace(" ", "_")
        path, _f = QFileDialog.getSaveFileName(self, "Export to Excel",
                                               f"{start}/{name}.xlsx",
                                               "Excel workbook (*.xlsx)")
        if not path:
            return
        self._remember(path)
        report = X.ExcelReport(
            project=self.session.project_name, author=self.author_edit.text().strip(),
            include_curves=self.chk_curves.isChecked(),
            include_charts=self.chk_charts.isChecked(),
            validation=V.run_all() if self.chk_validation.isChecked() else [],
            theme=self.session.theme,
            manual=[{"name": c.name, "inputs": c.input_text(), "value": c.value,
                     "unit": c.unit, "reference": c.reference} for c in self.session.manual],
        )
        for run in runs:
            report.add(X.RunRecord(run.sample, run.measurement, run.result,
                                   source=run.source, options=run.options))
        try:
            written = X.write_workbook(report, path)
        except Exception as exc:                                # noqa: BLE001
            self.session.status.emit(f"Excel export failed: {exc}", "error")
            return
        self.session.status.emit(f"Workbook written to {written.name}", "success")

    # -- Origin --------------------------------------------------------------
    def export_origin(self, force_script: bool = False) -> None:
        runs = self._selected_runs()
        if not runs:
            self.session.status.emit("Select at least one run to export.", "warning")
            return
        if self._thread is not None:
            self.session.status.emit("An Origin export is already running.", "warning")
            return
        start = self.session.settings.get("last_export_dir", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Choose an export folder", start)
        if not folder:
            return
        self._remember(folder + "/x")
        self.session.set_setting("origin_visible", self.chk_visible.isChecked())
        self.session.set_setting("origin_keep_open", self.chk_keep.isChecked())

        items = [O.OriginExportItem(r.sample, r.measurement, r.result, r.source) for r in runs]
        self.busy.start()
        self.btn_origin.setEnabled(False)
        self.btn_script.setEnabled(False)
        self.session.busy.emit(True, "Building the Origin project…")

        self._thread = QThread(self)
        self._worker = _OriginWorker(items, folder, self.session.palette_name,
                                     self.session.theme, self.chk_images.isChecked(),
                                     self.chk_visible.isChecked(), self.chk_keep.isChecked(),
                                     force_script)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._origin_done)
        self._thread.start()

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def wait_for_export(self, msec: int = 120_000) -> bool:
        """Let a running Origin export finish. Qt aborts if a live QThread is destroyed."""
        if self._thread is None:
            return True
        self._thread.quit()
        finished = self._thread.wait(msec)
        self._thread = None
        self._worker = None
        return finished

    def _origin_done(self, result, error: str) -> None:
        self.busy.stop()
        self.session.busy.emit(False, "")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
            self._worker = None
        self.btn_origin.setEnabled(True)
        self.btn_script.setEnabled(True)
        if error or result is None:
            self.session.status.emit(f"Origin export failed: {error.splitlines()[0] if error else 'unknown error'}",
                                     "error")
            return
        for message in result.messages:
            self.session.status.emit(message, "info")
        self.session.status.emit(result.summary(), "success")

    # -- figures -------------------------------------------------------------
    def export_images(self) -> None:
        runs = self._selected_runs()
        if not runs:
            self.session.status.emit("Select at least one run to export.", "warning")
            return
        start = self.session.settings.get("last_export_dir", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the figures", start)
        if not folder:
            return
        self._remember(folder + "/x")
        suffix = self.img_format.currentText().lower().replace("tiff", "tif")
        size = self.img_size.currentText()
        dpi = self.img_dpi.currentText()
        written = 0
        for run in runs:
            for plot in run.measurement.plots:
                try:
                    data = F.build_plot_data(plot, run.result, theme=self.session.theme,
                                             palette_name=self.session.palette_name,
                                             title=f"{run.sample} — {plot.title}")
                    if data.is_empty:
                        continue
                    figure = F.render_figure(data, theme=self.session.theme, size=size)
                    safe = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in run.sample)
                    F.save_figure(figure, Path(folder) / f"{safe}_{plot.id}.{suffix}", dpi=dpi)
                    written += 1
                except Exception as exc:                        # noqa: BLE001
                    self.session.status.emit(f"{run.sample}/{plot.id}: {exc}", "error")
        level = "success" if written else "warning"
        self.session.status.emit(f"Wrote {written} figure(s) to {folder}", level)
