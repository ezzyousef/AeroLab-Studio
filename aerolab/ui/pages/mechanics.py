"""Mechanics studio: deeper looks at the mechanical runs already analysed.

Pick a run and the page shows the analysis that fits it: modulus-window sensitivity for a
tensile curve, per-cycle energies for cyclic loading, Basquin-versus-Wöhler comparison
for S–N data, bootstrap intervals for strain–life constants, model comparison for
relaxation and creep, and any images linked to the run's experiment in the Workspace.
Everything is recomputed from the run's stored curves, so it works on reopened sessions.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QListWidget, QSplitter, QVBoxLayout, QWidget

from ...core import curves as C, mechanics as MX
from ...core.curves import AnalysisResult
from ...core.measurements import Plot, Series
from ..widgets import Card, PlotCanvas, ResultTable
from .base import Page

__all__ = ["MechanicsPage", "MECHANICAL_KINDS"]

MECHANICAL_KINDS = ("stress_strain", "cyclic_tension", "sn_curve", "strain_life", "stress_relaxation", "creep")


class MechanicsPage(Page):
    title = "Mechanics studio"
    subtitle = ("Window sensitivity, cycle energies, fatigue model comparison with bootstrap intervals, "
                "viscoelastic models and linked images. Fits never extend beyond the tested range.")
    glyph = "σ"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        top = QHBoxLayout()
        top.addWidget(QLabel("Run"))
        self.run_combo = QComboBox()
        self.run_combo.setAccessibleName("Mechanical run")
        self.run_combo.setMinimumWidth(360)
        self.run_combo.currentIndexChanged.connect(self._show)
        top.addWidget(self.run_combo, 1)
        self.content.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.summary_card = Card("Analysis")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary_card.body.addWidget(self.summary)
        self.table = ResultTable(["", "", "", "", "", ""])
        self.table.setMinimumHeight(200)
        self.summary_card.body.addWidget(self.table, 1)
        ll.addWidget(self.summary_card, 1)
        self.images_card = Card("Linked images", "Images attached to this run's experiment or sample (Workspace).")
        self.image_list = QListWidget()
        self.image_list.setAccessibleName("Linked images")
        self.image_list.currentRowChanged.connect(self._show_image)
        self.image_view = QLabel()
        self.image_view.setAlignment(Qt.AlignCenter)
        self.image_view.setMinimumHeight(140)
        self.images_card.body.addWidget(self.image_list)
        self.images_card.body.addWidget(self.image_view)
        ll.addWidget(self.images_card)
        split.addWidget(left)
        self.plot = PlotCanvas()
        split.addWidget(self.plot)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
        self.content.addWidget(split, 1)
        self._images: list = []
        self.last: dict = {}
        session.runs_changed.connect(self.refresh)
        session.workspace_changed.connect(self._show)

    # -- data ----------------------------------------------------------------
    def refresh(self) -> None:
        current = self.run_combo.currentData()
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        for run in self.session.runs:
            if run.measurement.id in MECHANICAL_KINDS:
                self.run_combo.addItem(run.title, run.run_id)
        self.run_combo.blockSignals(False)
        if self.run_combo.count():
            idx = max(0, self.run_combo.findData(current))
            self.run_combo.setCurrentIndex(idx)
        self._show()

    def select_run(self, run_id: int) -> None:
        idx = self.run_combo.findData(run_id)
        if idx >= 0:
            self.run_combo.setCurrentIndex(idx)
            self._show()

    def _show(self) -> None:
        run = self.session.run_by_id(self.run_combo.currentData()) if self.run_combo.count() else None
        self.last = {}
        if run is None:
            self.summary.setText("Analyse a tensile, cyclic, fatigue, relaxation or creep dataset first "
                                 "(Data → Analyse). This page then shows the deeper checks for it.")
            self.table.setColumnCount(0)
            self.table.setRowCount(0)
            self.plot.show_message("No mechanical run selected", self.session.theme)
            self._fill_images(None)
            return
        kind = run.measurement.id
        try:
            handler = {"stress_strain": self._tensile, "cyclic_tension": self._cyclic, "sn_curve": self._sn,
                       "strain_life": self._strain_life, "stress_relaxation": self._visco,
                       "creep": self._visco}[kind]
            handler(run)
        except Exception as exc:                            # noqa: BLE001 - shown to the user
            self.summary.setText(f"Could not analyse this run: {exc}")
            self.table.setRowCount(0)
            self.plot.show_message("—", self.session.theme)
        self._fill_images(run)

    def _set_table(self, headers, rows) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.fill(rows)

    def _draw(self, plot: Plot, curves: dict, kind: str) -> None:
        self.plot.show_plot(_plot_data(plot, AnalysisResult(kind, [], curves, {}), self.session.theme),
                            self.session.theme)

    # -- per kind ------------------------------------------------------------
    def _tensile(self, run) -> None:
        e, s = run.result.curves["stress-strain"]
        sens = MX.modulus_sensitivity(e, s)
        self.last = {"kind": "sensitivity", "result": sens}
        verdict = ("the modulus barely depends on the window" if sens["cv_pct"] < 5 else
                   "the modulus depends noticeably on the window — report the window with E" if sens["cv_pct"] < 15
                   else "the curve has no clear linear region; E is window-dependent and should be read with care")
        self.summary.setText(f"Young's modulus over {len(sens['windows'])} windows in the first 40 % of the strain "
                             f"at UTS: {sens['min']:.4g} – {sens['max']:.4g} MPa (mean {sens['mean']:.4g}, "
                             f"CV {sens['cv_pct']:.1f} %): {verdict}.")
        self._set_table(["Start (%)", "End (%)", "E (MPa)", "R²", "Points"],
                        [(w["start"], w["end"], w["E"], w["r2"], w["points"]) for w in sens["windows"]])
        starts = np.array([w["start"] for w in sens["windows"]])
        moduli = np.array([w["E"] for w in sens["windows"]])
        order = np.argsort(starts, kind="stable")
        self._draw(Plot("sens", "Modulus versus fit window", "Window start", "%", "Young's modulus", "MPa",
                        (Series("windows", "Each window", "scatter", "data"),)),
                   {"windows": (starts[order], moduli[order])}, "sensitivity")

    def _cyclic(self, run) -> None:
        rows = run.result.meta.get("per_cycle")
        if not rows:                                         # a reopened session: recompute from the loops
            loops = [run.result.curves[k] for k in run.result.curves if k.startswith("cycle")]
            e = np.concatenate([np.asarray(x, float) for x, _ in loops])
            s = np.concatenate([np.asarray(y, float) for _, y in loops])
            rows = C.analyze_cyclic_tension(e, s).meta["per_cycle"]
        self.last = {"kind": "cycles", "rows": rows}
        total = sum(r["hysteresis_energy"] for r in rows)
        self.summary.setText(f"{len(rows)} cycles; dissipated energy {total:.4g} MJ/m³ in total. Energies are "
                             "loop areas in stress × strain (MPa × mm/mm = MJ/m³).")
        self._set_table(["Cycle", "Peak strain (%)", "Loading (MJ/m³)", "Unloading (MJ/m³)", "Hysteresis (MJ/m³)",
                         "Dissipation (%)", "Permanent set (%)"],
                        [(r["cycle"], r["peak_strain"], r.get("loading_energy", float("nan")),
                          r.get("unloading_energy", float("nan")), r["hysteresis_energy"],
                          r["dissipation_ratio"], r["permanent_set"]) for r in rows])
        cyc = np.array([r["cycle"] for r in rows], float)
        self._draw(Plot("energy", "Energy per cycle", "Cycle", "", "Energy", "MJ/m³",
                        (Series("hysteresis", "Hysteresis (dissipated)", "scatter+line", "data"),
                         Series("loading", "Loading work", "scatter+line", "data"))),
                   {"hysteresis": (cyc, np.array([r["hysteresis_energy"] for r in rows])),
                    "loading": (cyc, np.array([r.get("loading_energy", np.nan) for r in rows]))}, "cycles")

    def _sn(self, run) -> None:
        two_n, sa = run.result.curves["data"]
        res = MX.compare_sn_models(np.asarray(two_n) / 2.0, sa, bootstrap=600)
        self.last = {"kind": "sn", "result": res}
        lo, hi = res.meta["calibration_range"]
        self.summary.setText(next(m.note for m in res.metrics if m.name == "Preferred S–N model")
                             + f" Tested range: {lo:.3g} – {hi:.3g} reversals.")
        self._set_table(["Quantity", "Value", "Unit", "Note"], [m.as_row() for m in res.metrics])
        plot = Plot("cmp", "S–N model comparison", "Reversals to failure 2N", "reversals", "Stress amplitude", "MPa",
                    (Series("data", "Measured", "scatter", "data"),
                     Series("Basquin σa = σ′f(2N)^b", "Basquin", "line", "fit"),
                     Series("Wöhler σa = A + B·log₁₀(2N)", "Wöhler", "line", "fit")), xscale="log", yscale="log")
        self._draw(plot, res.curves, "sn_comparison")

    def _strain_life(self, run) -> None:
        two_n, ea = run.result.curves["elastic data"]
        _, pa = run.result.curves["plastic data"]
        ci = MX.strain_life_bootstrap(np.asarray(two_n) / 2.0, ea, pa, bootstrap=600)
        self.last = {"kind": "strain_life", "result": ci}
        self.summary.setText("Bootstrap over specimens (600 resamples, percentile 95 % intervals). The fitted "
                             "branches are drawn over the tested lives only.")
        self._set_table(["Constant", "Estimate", "95 % low", "95 % high"],
                        [(k, v[0], v[1], v[2]) for k, v in ci.items()])
        plot = Plot("sl", "Strain–life", "Reversals to failure 2N", "reversals", "Strain amplitude", "-",
                    (Series("elastic data", "Elastic", "scatter", "data"),
                     Series("plastic data", "Plastic", "scatter", "data"),
                     Series("elastic fit", "Elastic branch", "line", "fit"),
                     Series("plastic fit", "Plastic branch", "line", "fit")), xscale="log", yscale="log")
        self._draw(plot, run.result.curves, "strain_life")

    def _visco(self, run) -> None:
        fits = run.result.meta.get("fits")
        t, y = run.result.curves["data"]
        if not fits:
            fn = MX.fit_relaxation if run.measurement.id == "stress_relaxation" else MX.fit_creep
            fits = [{"name": f.name, "params": f.params, "aic": f.aic, "bic": f.bic, "r2": f.r2,
                     "assumption": f.assumption} for f in fn(t, y)]
        self.last = {"kind": "visco", "fits": fits}
        best = fits[0]
        self.summary.setText(f"Best by AIC: {best['name']} — {best['assumption']}. {MX.VISCO_ASSUMPTIONS}")
        self._set_table(["Model", "ΔAIC", "BIC", "R²", "Parameters"],
                        [(f["name"], f["aic"] - best["aic"], f["bic"], f["r2"],
                          ", ".join(f"{k} = {v:.4g}" for k, v in f["params"].items())) for f in fits])
        plot = run.measurement.plots[0]
        self._draw(plot, run.result.curves, run.measurement.id)

    # -- images ----------------------------------------------------------------
    def _fill_images(self, run) -> None:
        self.image_list.clear()
        self.image_view.clear()
        self._images = []
        if run is None:
            return
        ws = self.session.workspace
        exp = ws.experiment_for_run(run.key)
        images = ws.images_for(sample_id=exp.sample_id if exp else "", experiment_id=exp.experiment_id if exp else "")
        self._images = images
        for a in images:
            self.image_list.addItem(f"{a.name}  ({a.experiment_id or a.sample_id})")
        if not images:
            self.image_view.setText("No image linked. In the Workspace, attach an SEM or specimen image to this "
                                    "run's experiment." if exp else
                                    "This run is not linked to an experiment yet (Workspace → Add experiment).")
        else:
            self.image_list.setCurrentRow(0)

    def _show_image(self, row: int) -> None:
        if not (0 <= row < len(self._images)):
            return
        pix = QPixmap(self._images[row].path)
        if pix.isNull():
            self.image_view.setText(f"Cannot display {self._images[row].name} (missing or not an image).")
        else:
            self.image_view.setPixmap(pix.scaled(360, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def on_theme_changed(self, theme: str) -> None:
        self._show()


def _plot_data(plot, result, theme):
    from ...viz.figures import build_plot_data
    return build_plot_data(plot, result, theme=theme)
