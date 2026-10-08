"""Measurements page: every analysed run, its numbers, its settings and its graph.

Changing a setting re-runs the analyser on the spot, so you can see what a different BET
window or heating rate does to the answer without re-importing anything.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from ...core import measurements as M
from ...viz import figures as F
from ..widgets import Card, EmptyState, OptionEditor, PlotCanvas, ResultTable, scrollable
from .base import Page

__all__ = ["MeasurePage"]


class MeasurePage(Page):
    title = "Measurements"
    subtitle = "Results, settings and graphs for every analysed dataset."
    glyph = "◴"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        self._option_editor: OptionEditor | None = None
        self._build()
        session.runs_changed.connect(self.refresh)
        self.refresh()

    def _build(self) -> None:
        self.btn_remove = QPushButton("Remove run")
        self.btn_remove.setObjectName("Danger")
        self.btn_remove.clicked.connect(self._remove)
        self.actions.addWidget(self.btn_remove)

        self.empty = EmptyState("◴", "No measurements yet",
                                "Import data and analyse it, or load the bundled demo "
                                "datasets to see every measurement at work.",
                                "Go to Data")
        self.empty.action.connect(lambda: self.navigate.emit("data"))
        self.content.addWidget(self.empty, 1)

        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)

        left = Card("Runs")
        left.setMinimumWidth(246)
        self.run_list = QListWidget()
        self.run_list.setWordWrap(True)
        self.run_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.run_list.currentRowChanged.connect(self._show_current)
        left.body.addWidget(self.run_list, 1)
        self.split.addWidget(left)

        right = QTabWidget()

        # --- results tab
        results = QWidget()
        rl = QVBoxLayout(results)
        rl.setContentsMargins(12, 12, 12, 12)
        rl.setSpacing(10)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("Hint")
        self.summary_label.setWordWrap(True)
        rl.addWidget(self.summary_label)
        self.metrics_table = ResultTable(["Quantity", "Value", "Unit", "Note"])
        rl.addWidget(self.metrics_table, 1)
        right.addTab(results, "Results")

        # --- graph tab
        plots = QWidget()
        pl = QVBoxLayout(plots)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(8)
        picker = QHBoxLayout()
        picker.addWidget(QLabel("Graph"))
        self.plot_combo = QComboBox()
        self.plot_combo.currentIndexChanged.connect(self._draw)
        picker.addWidget(self.plot_combo, 1)
        self.btn_save_fig = QPushButton("Save image…")
        self.btn_save_fig.clicked.connect(self._save_figure)
        picker.addWidget(self.btn_save_fig)
        pl.addLayout(picker)
        self.canvas = PlotCanvas()
        pl.addWidget(self.canvas, 1)
        right.addTab(plots, "Graph")

        # --- settings tab
        self.settings_host = QWidget()
        sl = QVBoxLayout(self.settings_host)
        sl.setContentsMargins(12, 12, 12, 12)
        sl.setSpacing(10)
        self.settings_hint = QLabel()
        self.settings_hint.setObjectName("Hint")
        self.settings_hint.setWordWrap(True)
        sl.addWidget(self.settings_hint)
        self.options_slot = QVBoxLayout()
        sl.addLayout(self.options_slot)
        rerun = QHBoxLayout()
        self.btn_rerun = QPushButton("Re-run with these settings")
        self.btn_rerun.setObjectName("Primary")
        self.btn_rerun.clicked.connect(self._rerun)
        rerun.addWidget(self.btn_rerun)
        rerun.addStretch(1)
        sl.addLayout(rerun)
        sl.addStretch(1)
        right.addTab(self.settings_host, "Settings")

        self.split.addWidget(right)
        self.split.setStretchFactor(0, 2)
        self.split.setStretchFactor(1, 6)
        self.content.addWidget(self.split, 1)

    # -- data ----------------------------------------------------------------
    def refresh(self) -> None:
        has_runs = bool(self.session.runs)
        self.empty.setVisible(not has_runs)
        self.split.setVisible(has_runs)
        self.btn_remove.setEnabled(has_runs)
        row = self.run_list.currentRow()
        self.run_list.blockSignals(True)
        self.run_list.clear()
        for run in self.session.runs:
            item = QListWidgetItem(f"{run.sample}\n{run.measurement.name}")
            item.setData(Qt.UserRole, run.run_id)
            self.run_list.addItem(item)
        self.run_list.blockSignals(False)
        if has_runs:
            self.run_list.setCurrentRow(min(max(row, 0), len(self.session.runs) - 1))
            self._show_current()

    def current_run(self):
        row = self.run_list.currentRow()
        if 0 <= row < len(self.session.runs):
            return self.session.runs[row]
        return None

    def _show_current(self, *_args) -> None:
        run = self.current_run()
        if run is None:
            return
        self.set_subtitle(f"{run.sample} — {run.measurement.summary}")
        bits = [run.measurement.name]
        if run.source:
            bits.append(Path(run.source).name)          # the full path wraps to three lines
        if run.measurement.reference:
            bits.append(f"Method: {run.measurement.reference}")
        self.summary_label.setText("   ·   ".join(bits))
        self.summary_label.setToolTip(run.source or run.sample)
        self.metrics_table.fill([(m.name, m.value, m.unit or "-", m.note)
                                 for m in run.result.metrics])

        self.plot_combo.blockSignals(True)
        self.plot_combo.clear()
        for plot in run.measurement.plots:
            self.plot_combo.addItem(plot.title, plot.id)
        self.plot_combo.blockSignals(False)
        self._draw()
        self._build_options(run)

    def _build_options(self, run) -> None:
        while self.options_slot.count():
            item = self.options_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not run.measurement.options:
            self.settings_hint.setText("This measurement has no adjustable settings.")
            self.btn_rerun.setEnabled(False)
            self._option_editor = None
            return
        self.settings_hint.setObjectName("Hint")
        self.settings_hint.style().unpolish(self.settings_hint)
        self.settings_hint.style().polish(self.settings_hint)
        self.settings_hint.setText(
            "Change a setting and re-run — the original data is kept, so this is free to try.")
        self.btn_rerun.setEnabled(run.measurement.kind != "table")
        self._option_editor = OptionEditor(
            run.measurement.options,
            values=M.upgrade_options(run.measurement.id, {**run.measurement.defaults(), **run.options}))
        self._option_editor.changed.connect(self._settings_edited)
        self.options_slot.addWidget(self._option_editor)

    def _settings_edited(self) -> None:
        # Until Re-run is pressed the numbers on screen belong to the old settings.
        self.settings_hint.setText("Settings changed — the results shown still use the previous "
                                   "settings. Press Re-run to update them.")
        self.settings_hint.setObjectName("PillWarn")
        self.settings_hint.style().unpolish(self.settings_hint)
        self.settings_hint.style().polish(self.settings_hint)

    def _draw(self) -> None:
        run = self.current_run()
        if run is None or not run.measurement.plots:
            self.canvas.show_message("This measurement has no graph.", self.session.theme)
            return
        plot_id = self.plot_combo.currentData()
        plot = next((p for p in run.measurement.plots if p.id == plot_id),
                    run.measurement.plots[0])
        data = F.build_plot_data(plot, run.result, theme=self.session.theme,
                                 palette_name=self.session.palette_name,
                                 title=f"{run.sample} — {plot.title}")
        if data.is_empty:
            self.canvas.show_message("No curves to draw for this run.", self.session.theme)
            return
        self.canvas.show_plot(data, theme=self.session.theme, metrics=run.result.metrics)

    def _rerun(self) -> None:
        run = self.current_run()
        if run is None or self._option_editor is None:
            return
        dataset = next((d for d in self.session.datasets if d.name == run.dataset_name), None)
        if dataset is None:
            self.session.status.emit(
                "The original dataset is no longer loaded — re-import it to change settings.",
                "warning")
            return
        options = self._option_editor.values()
        try:
            data, notes = M.prepare_data(run.measurement, dataset.columns, dataset.units, run.mapping)
            result = run.measurement.run(data, **options)
            if notes:
                result.meta["import_notes"] = notes
        except Exception as exc:                                # noqa: BLE001 - shown to the user
            self.session.status.emit(f"Re-run failed: {exc}", "error")
            return
        self.session.replace_run_result(
            run, result, {k: v for k, v in options.items() if v is not None})
        self.session.status.emit(f"Re-ran {run.sample} with the new settings", "success")

    def _remove(self) -> None:
        run = self.current_run()
        if run is not None:
            self.session.remove_run(run.run_id)

    def _save_figure(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        run = self.current_run()
        if run is None:
            return
        start = self.session.settings.get("last_export_dir", "")
        path, _f = QFileDialog.getSaveFileName(
            self, "Save figure", f"{start}/{run.sample}_{self.plot_combo.currentData()}.png",
            "PNG image (*.png);;PDF document (*.pdf);;SVG vector (*.svg);;TIFF image (*.tif)")
        if not path:
            return
        try:
            self.canvas.save(path, dpi=self.session.settings.get("export_dpi", "print"))
            self.session.status.emit(f"Saved {path}", "success")
        except Exception as exc:                                # noqa: BLE001
            self.session.status.emit(f"Could not save the figure: {exc}", "error")

    def on_theme_changed(self, theme: str) -> None:
        self._draw()
