"""Plots page: put several runs on one pair of axes and compare them.

The comparison view is what the papers actually show — four fibre grades on one
stress–strain plot — so it gets its own page rather than being buried in Measurements.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from ...core.measurements import Plot, Series
from ...viz import figures as F, style as S
from ..widgets import Card, EmptyState, PlotCanvas, scrollable
from .base import Page

__all__ = ["PlotsPage"]


class PlotsPage(Page):
    title = "Plots"
    subtitle = "Overlay several runs on one figure, the way a paper compares samples."
    glyph = "◭"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        self._build()
        session.runs_changed.connect(self.refresh)
        self.refresh()

    def _build(self) -> None:
        self.btn_save = QPushButton("Save image…")
        self.btn_save.clicked.connect(self._save)
        self.btn_draw = QPushButton("Draw")
        self.btn_draw.setObjectName("Primary")
        self.btn_draw.clicked.connect(self._draw)
        self.actions.addWidget(self.btn_save)
        self.actions.addWidget(self.btn_draw)

        self.empty = EmptyState("◭", "Nothing to compare yet",
                                "Analyse two or more datasets of the same kind and they can "
                                "be overlaid here.", "Go to Data")
        self.empty.action.connect(lambda: self.navigate.emit("data"))
        self.content.addWidget(self.empty, 1)

        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)

        left = Card("Choose runs", "Only runs of the same measurement can share axes.")
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Measurement"))
        self.kind_combo = QComboBox()
        self.kind_combo.currentIndexChanged.connect(self._on_kind)
        pick.addWidget(self.kind_combo, 1)
        left.body.addLayout(pick)

        graph_row = QHBoxLayout()
        graph_row.addWidget(QLabel("Graph"))
        self.plot_combo = QComboBox()
        self.plot_combo.currentIndexChanged.connect(self._draw)
        graph_row.addWidget(self.plot_combo, 1)
        left.body.addLayout(graph_row)

        self.run_list = QListWidget()
        self.run_list.itemChanged.connect(lambda _i: self._draw())
        left.body.addWidget(self.run_list, 1)

        toggles = QHBoxLayout()
        self.chk_fits = QCheckBox("Show fits")
        self.chk_fits.setChecked(True)
        self.chk_fits.toggled.connect(self._draw)
        self.chk_legend = QCheckBox("Legend")
        self.chk_legend.setChecked(True)
        self.chk_legend.toggled.connect(self._draw)
        toggles.addWidget(self.chk_fits)
        toggles.addWidget(self.chk_legend)
        toggles.addStretch(1)
        left.body.addLayout(toggles)

        buttons = QHBoxLayout()
        btn_all = QPushButton("Select all")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("Select none")
        btn_none.clicked.connect(lambda: self._set_all(False))
        buttons.addWidget(btn_all)
        buttons.addWidget(btn_none)
        buttons.addStretch(1)
        left.body.addLayout(buttons)
        self.split.addWidget(left)

        right = Card("Figure")
        self.canvas = PlotCanvas()
        right.body.addWidget(self.canvas, 1)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 2)
        self.split.setStretchFactor(1, 6)
        self.content.addWidget(self.split, 1)

    # -- data ----------------------------------------------------------------
    def refresh(self) -> None:
        kinds: dict[str, str] = {}
        for run in self.session.runs:
            if run.measurement.plots:
                kinds[run.measurement.id] = run.measurement.name
        has = bool(kinds)
        self.empty.setVisible(not has)
        self.split.setVisible(has)
        self.btn_draw.setEnabled(has)
        self.btn_save.setEnabled(has)
        if not has:
            return

        current = self.kind_combo.currentData()
        self.kind_combo.blockSignals(True)
        self.kind_combo.clear()
        for mid, name in kinds.items():
            count = sum(1 for r in self.session.runs if r.measurement.id == mid)
            self.kind_combo.addItem(f"{name}  ({count})", mid)
        index = self.kind_combo.findData(current)
        self.kind_combo.setCurrentIndex(max(0, index))
        self.kind_combo.blockSignals(False)
        self._on_kind()

    def _on_kind(self) -> None:
        mid = self.kind_combo.currentData()
        runs = [r for r in self.session.runs if r.measurement.id == mid]
        self.run_list.blockSignals(True)
        self.run_list.clear()
        for run in runs:
            item = QListWidgetItem(run.sample)
            item.setData(Qt.UserRole, run.run_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if len(runs) <= 8 else Qt.Unchecked)
            self.run_list.addItem(item)
        self.run_list.blockSignals(False)

        if runs:
            self.plot_combo.blockSignals(True)
            self.plot_combo.clear()
            for plot in runs[0].measurement.plots:
                self.plot_combo.addItem(plot.title, plot.id)
            self.plot_combo.blockSignals(False)
        self._draw()

    def _set_all(self, checked: bool) -> None:
        self.run_list.blockSignals(True)
        for i in range(self.run_list.count()):
            self.run_list.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.run_list.blockSignals(False)
        self._draw()

    def _selected_runs(self) -> list:
        ids = {self.run_list.item(i).data(Qt.UserRole)
               for i in range(self.run_list.count())
               if self.run_list.item(i).checkState() == Qt.Checked}
        return [r for r in self.session.runs if r.run_id in ids]

    # -- drawing -------------------------------------------------------------
    def _draw(self) -> None:
        runs = self._selected_runs()
        if not runs:
            self.canvas.show_message("Tick one or more runs to draw.", self.session.theme)
            return
        plot_id = self.plot_combo.currentData()
        template = next((p for p in runs[0].measurement.plots if p.id == plot_id),
                        runs[0].measurement.plots[0])

        merged, roles = _merge(runs, template, show_fits=self.chk_fits.isChecked())
        if not merged:
            self.canvas.show_message("The selected runs have no curves for this graph.",
                                     self.session.theme)
            return

        combined = Plot(template.id, f"{runs[0].measurement.name} — {len(runs)} sample(s)",
                        template.x_label, template.x_unit, template.y_label, template.y_unit,
                        tuple(Series(key, key, _hint(template, roles[key]), roles[key])
                              for key in merged),
                        template.xscale, template.yscale, template.note)
        from ...core.curves import AnalysisResult
        holder = AnalysisResult("comparison", [], merged, {})
        data = F.build_plot_data(combined, holder, theme=self.session.theme,
                                 palette_name=self.session.palette_name)
        self.canvas.show_plot(data, theme=self.session.theme,
                              legend=self.chk_legend.isChecked())

    def _save(self) -> None:
        start = self.session.settings.get("last_export_dir", "")
        path, _f = QFileDialog.getSaveFileName(
            self, "Save comparison figure", f"{start}/comparison.png",
            "PNG image (*.png);;PDF document (*.pdf);;SVG vector (*.svg)")
        if not path:
            return
        try:
            self.canvas.save(path, dpi=self.session.settings.get("export_dpi", "print"))
            self.session.status.emit(f"Saved {path}", "success")
        except Exception as exc:                                # noqa: BLE001
            self.session.status.emit(f"Could not save the figure: {exc}", "error")

    def on_theme_changed(self, theme: str) -> None:
        self._draw()


def _merge(runs, template: Plot, show_fits: bool):
    """Gather the curves of several runs under names that identify their sample."""
    merged: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    roles: dict[str, str] = {}
    wanted = [(s.curve, s.role) for s in template.series]
    for run in runs:
        for curve_key, role in wanted:
            if role == "fit" and not show_fits:
                continue
            keys = list(run.result.curves) if curve_key == "*" else [curve_key]
            for key in keys:
                if key not in run.result.curves:
                    continue
                label = run.sample if len(keys) == 1 else f"{run.sample} · {key}"
                if role == "fit":
                    label = f"{label} fit"
                merged[label] = run.result.curves[key]
                roles[label] = role
    return merged, roles


def _hint(template: Plot, role: str) -> str:
    if role == "fit":
        return "line"
    return template.series[0].style if template.series else "scatter"
