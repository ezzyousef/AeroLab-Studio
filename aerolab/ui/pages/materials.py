"""Materials studio: multi-event TGA/DSC tables, porosity summaries, k–density, LVER and QC.

QC flags are shown for every run, mechanical ones included, because a missing calibration
record matters whatever was measured. Crystallinity is computed only from a ΔH°m the user
types in. No reference enthalpy is assumed, since values for TPU hard segments vary
widely in the literature.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from ...core import materials as MT
from ..widgets import Card, PlotCanvas, ResultTable
from .base import Page

__all__ = ["MaterialsPage"]


class MaterialsPage(Page):
    title = "Materials studio"
    subtitle = ("Decomposition steps, DSC events and crystallinity, porosity from N₂ and from densities, "
                "k versus density, the linear viscoelastic region, and QC flags for every run.")
    glyph = "Δ"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        top = QHBoxLayout()
        top.addWidget(QLabel("Run"))
        self.run_combo = QComboBox()
        self.run_combo.setAccessibleName("Run")
        self.run_combo.setMinimumWidth(360)
        self.run_combo.currentIndexChanged.connect(self._show)
        top.addWidget(self.run_combo, 1)
        top.addWidget(QLabel("Sample"))
        self.sample_combo = QComboBox()
        self.sample_combo.setAccessibleName("Workspace sample for densities")
        self.sample_combo.setToolTip("Densities for the porosity summary come from this Workspace sample")
        self.sample_combo.currentIndexChanged.connect(self._show)
        top.addWidget(self.sample_combo)
        self.content.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.card = Card("Analysis")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.card.body.addWidget(self.summary)
        self.dsc_row = QWidget()
        dr = QHBoxLayout(self.dsc_row)
        dr.setContentsMargins(0, 0, 0, 0)
        self.polymer_fraction = QLineEdit()
        self.polymer_fraction.setPlaceholderText("polymer mass fraction (0–1)")
        self.polymer_fraction.setAccessibleName("Polymer mass fraction")
        self.dh100 = QLineEdit()
        self.dh100.setPlaceholderText("ΔH°m of 100 % crystal, J/g")
        self.dh100.setAccessibleName("Enthalpy of a fully crystalline polymer")
        recalc = QPushButton("Recalculate")
        recalc.clicked.connect(self._show)
        dr.addWidget(self.polymer_fraction)
        dr.addWidget(self.dh100)
        dr.addWidget(recalc)
        self.card.body.addWidget(self.dsc_row)
        self.table = ResultTable(["", ""])
        self.table.setMinimumHeight(180)
        self.card.body.addWidget(self.table, 1)
        ll.addWidget(self.card, 1)
        qc = Card("QC flags", "Checks on calibration, traceability and the analysis itself.")
        self.flags = QListWidget()
        self.flags.setAccessibleName("QC flags")
        qc.body.addWidget(self.flags)
        ll.addWidget(qc)
        split.addWidget(left)
        self.plot = PlotCanvas()
        split.addWidget(self.plot)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
        self.content.addWidget(split, 1)
        self.last: dict = {}
        session.runs_changed.connect(self.refresh)
        session.workspace_changed.connect(self.refresh)

    def refresh(self) -> None:
        cur_run, cur_sample = self.run_combo.currentData(), self.sample_combo.currentData()
        for combo in (self.run_combo, self.sample_combo):
            combo.blockSignals(True)
            combo.clear()
        for run in self.session.runs:
            self.run_combo.addItem(run.title, run.run_id)
        self.sample_combo.addItem("(none)", "")
        for s in self.session.workspace.samples.values():
            self.sample_combo.addItem(s.sample_id, s.sample_id)
        for combo, cur in ((self.run_combo, cur_run), (self.sample_combo, cur_sample)):
            idx = combo.findData(cur)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)
        self._show()

    def select_run(self, run_id: int) -> None:
        idx = self.run_combo.findData(run_id)
        if idx >= 0:
            self.run_combo.setCurrentIndex(idx)

    def _sample(self, run):
        ws = self.session.workspace
        sid = self.sample_combo.currentData()
        if sid:
            return ws.samples.get(sid)
        exp = ws.experiment_for_run(run.key) if run else None
        return ws.samples.get(exp.sample_id) if exp else None

    def _show(self) -> None:
        run = self.session.run_by_id(self.run_combo.currentData()) if self.run_combo.count() else None
        self.last = {}
        self.dsc_row.setVisible(bool(run and run.measurement.id == "dsc"))
        self.flags.clear()
        if run is None:
            self.summary.setText("Analyse a dataset first (Data → Analyse).")
            self.table.setRowCount(0)
            self.plot.show_message("No run selected", self.session.theme)
            return
        kind = run.measurement.id
        try:
            {"tga": self._tga, "dsc": self._dsc, "sorption": self._sorption, "crossover": self._lver,
             "k_density": self._kdens}.get(kind, self._generic)(run)
        except Exception as exc:                            # noqa: BLE001 - shown to the user
            self.summary.setText(f"Could not analyse this run: {exc}")
            self.table.setRowCount(0)
        if kind in ("tga", "dsc", "sorption", "crossover", "k_density"):
            plot = run.measurement.plots[0]
            from ...viz.figures import build_plot_data
            self.plot.show_plot(build_plot_data(plot, run.result, theme=self.session.theme), self.session.theme)
        else:
            self.plot.show_message("See the Measurements page for this run's graphs", self.session.theme)
        self._qc(run)

    def _set(self, headers, rows):
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.fill(rows)

    def _tga(self, run):
        T, w = run.result.curves["TGA"]
        steps = MT.tga_steps(T, w)
        self.last = {"kind": "tga", "steps": steps}
        self.summary.setText(f"{len(steps)} decomposition step(s), split at the DTG valleys. Losses are % of the "
                             "initial weight and add up to the total loss.")
        self._set(["Step", "From (°C)", "To (°C)", "DTG peak (°C)", "Mass loss (%)"],
                  [(i, s["start"], s["end"], s["peak"], s["loss"]) for i, s in enumerate(steps, start=1)])

    def _dsc(self, run):
        transitions = run.result.meta.get("transitions")
        if transitions is None:
            from ...core.curves import analyze_dsc
            T, q = run.result.curves["DSC"]
            # stored q already has the sign and mass normalisation applied
            transitions = analyze_dsc(T, q, heating_rate=float(run.options.get("heating_rate") or 10.0)
                                      ).meta["transitions"]
        pf, dh = _num(self.polymer_fraction.text()), _num(self.dh100.text())
        rows = MT.dsc_event_table(transitions, polymer_fraction=pf, dh100=dh)
        self.last = {"kind": "dsc", "rows": rows}
        self.summary.setText("Every transition, integrated against the chord through its own limits. "
                             + ("Crystallinity uses your ΔH°m." if dh else
                                "Enter ΔH°m (and the polymer fraction) for crystallinity; none is assumed."))
        self._set(["Event", "Kind", "Peak (°C)", "Range (°C)", "ΔH (J/g)", "ΔH per polymer (J/g)", "Xc (%)"],
                  [(r["event"], r["kind"], r["peak"], f"{r['onset']:.1f}–{r['end']:.1f}", r["enthalpy"],
                    r["enthalpy_per_polymer"], r["crystallinity"]) for r in rows])

    def _sorption(self, run):
        sample = self._sample(run)
        rho_b = sample.bulk_density_g_cm3 if sample else None
        derived = sample.derived() if sample else {}
        rho_s = derived.get("skeletal density", {}).get("value") if derived else None
        out = MT.porosity_summary(run.result.value("BET surface area"), run.result.value("Total pore volume"),
                                  rho_b, rho_s)
        self.last = {"kind": "porosity", "summary": out}
        self.summary.setText("Gas sorption and densities describe the same pore space in two ways."
                             + ("" if rho_b and rho_s else " Pick a Workspace sample with bulk and skeletal "
                                                            "densities (or components) to add the density view."))
        self._set(["Quantity", "Value", "Unit", "Source"],
                  [(k, v["value"], v["unit"], v["source"]) for k, v in out.items()])

    def _lver(self, run):
        x, gp = run.result.curves["G'"]
        lv = MT.lver_limit(x, gp)
        self.last = {"kind": "lver", "result": lv}
        unit = run.options.get("x_unit") or "Pa"
        self.summary.setText(f"Plateau G′ {lv['plateau']:.4g} Pa; G′ leaves the ±10 % band at "
                             + (f"{lv['limit']:.4g} {unit}." if math.isfinite(lv["limit"]) else
                                "no point within the sweep (still linear)."))
        self._set(["Quantity", "Value", "Unit", "Note"], [m.as_row() for m in run.result.metrics])

    def _kdens(self, run):
        self.last = {"kind": "k_density"}
        self.summary.setText("Three k(ρ) models compared by AIC; the minimum is reported only inside the data.")
        self._set(["Quantity", "Value", "Unit", "Note"], [m.as_row() for m in run.result.metrics])

    def _generic(self, run):
        self.last = {"kind": "generic"}
        self.summary.setText("No materials-specific view for this measurement; its results and QC flags are below.")
        self._set(["Quantity", "Value", "Unit", "Note"], [m.as_row() for m in run.result.metrics])

    def _qc(self, run):
        ws = self.session.workspace
        exp = ws.experiment_for_run(run.key)
        sample = ws.samples.get(exp.sample_id) if exp else None
        flags = MT.qc_flags(run.measurement.id, run.result, run.options, experiment=exp, sample=sample)
        self.last["flags"] = flags
        if not flags:
            self.flags.addItem("No flags: calibration recorded and current, analysis checks passed.")
        for level, message in flags:
            item = QListWidgetItem(("⚠ " if level == "warning" else "ℹ ") + message)
            item.setToolTip(message)
            self.flags.addItem(item)

    def on_theme_changed(self, theme: str) -> None:
        self._show()


def _num(text: str) -> float | None:
    try:
        return float(text.strip().replace(",", ".")) if text and text.strip() else None
    except ValueError:
        return None
