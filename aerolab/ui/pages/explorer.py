"""Experiment explorer: compare batches, response surfaces, sensitivity and π groups,
design-of-experiments suggestions, publishable reports and export verification.

The DOE tab only proposes settings. It never fills in results. The response surface
is fitted to analysed runs whose Workspace sample records the two factors.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ...core import equations as E, explorer as X, validation as V
from ..widgets import Card, PlotCanvas, ResultTable
from .base import Page

__all__ = ["ExplorerPage"]


def _cell(t: QTableWidget, r: int, c: int) -> str:
    it = t.item(r, c)
    return it.text().strip() if it else ""


class ExplorerPage(Page):
    title = "Explorer"
    subtitle = ("Compare batches, fit response surfaces to your own results, rank sensitivities, find "
                "dimensionless groups, plan experiments and write a report with full provenance.")
    glyph = "∑"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        for label, slot in (("Write report…", lambda: self.write_report()),
                            ("Verify an Excel export…", lambda: self.verify_excel())):
            b = QPushButton(label)
            b.clicked.connect(slot)
            self.actions.addWidget(b)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._batches_tab(), "Compare batches")
        self.tabs.addTab(self._surface_tab(), "Response surface")
        self.tabs.addTab(self._sensitivity_tab(), "Sensitivity && dimensions")
        self.tabs.addTab(self._doe_tab(), "Design of experiments")
        self.content.addWidget(self.tabs, 1)
        self.last: dict = {}
        session.runs_changed.connect(self.refresh)
        session.workspace_changed.connect(self.refresh)

    # -- batches ---------------------------------------------------------------
    def _batches_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.metric_combo = QComboBox()
        self.metric_combo.setAccessibleName("Metric to compare")
        self.metric_combo.setMinimumWidth(320)
        self.metric_combo.currentIndexChanged.connect(self.compare)
        self.ref_combo = QComboBox()
        self.ref_combo.setAccessibleName("Reference sample")
        self.ref_combo.currentIndexChanged.connect(self.compare)
        row.addWidget(QLabel("Metric"))
        row.addWidget(self.metric_combo, 1)
        row.addWidget(QLabel("Reference"))
        row.addWidget(self.ref_combo)
        lay.addLayout(row)
        self.batch_note = QLabel()
        self.batch_note.setWordWrap(True)
        self.batch_note.setObjectName("Hint")
        lay.addWidget(self.batch_note)
        self.values_table = ResultTable(["Sample", "Batch", "Value", "Unit", "Relative", "Per density", "Specific rel."])
        self.group_table = ResultTable(["Batch", "n", "Mean", "SD", "95 % CI low", "95 % CI high", "CV (%)"])
        lay.addWidget(self.values_table, 2)
        lay.addWidget(self.group_table, 1)
        return w

    def _batch_of(self, run) -> tuple[str, float | None]:
        ws = self.session.workspace
        exp = ws.experiment_for_run(run.key)
        s = ws.samples.get(exp.sample_id) if exp else ws.samples.get(run.sample)
        if s is None:
            return run.sample, None
        root = s.replicate_of or s.sample_id
        return (s.batch or root), s.bulk_density_g_cm3

    def compare(self) -> None:
        name = self.metric_combo.currentData()
        rows, by_batch, unit = [], {}, ""
        for run in self.session.runs:
            for m in run.result.metrics:
                if m.name == name and isinstance(m.value, float) and math.isfinite(m.value):
                    batch, rho = self._batch_of(run)
                    rows.append({"sample": run.sample, "batch": batch, "value": m.value, "density": rho})
                    by_batch.setdefault(batch, []).append(m.value)
                    unit = m.unit
        ref = self.ref_combo.currentData()
        try:
            norm = X.normalised_comparison(rows, ref) if ref and rows else []
        except ValueError:
            norm = []
        nmap = {r["sample"]: r for r in norm}
        self.values_table.fill([(r["sample"], r["batch"], r["value"], unit,
                                 nmap.get(r["sample"], {}).get("relative", float("nan")),
                                 nmap.get(r["sample"], {}).get("specific", float("nan")),
                                 nmap.get(r["sample"], {}).get("specific_relative", float("nan"))) for r in rows])
        stats_ = X.group_statistics(by_batch)
        self.group_table.fill([(b, int(s["n"]), s["mean"], s["sd"], s["ci95_low"], s["ci95_high"], s["cv_pct"])
                               for b, s in stats_.items()])
        anova = X.one_way_anova(by_batch)
        text = f"{len(rows)} value(s) in {len(by_batch)} batch(es). Batches come from the Workspace (batch, or the parent of a replicate)."
        if math.isfinite(anova["p"]):
            text += f" One-way ANOVA over batches with ≥2 values: F = {anova['F']:.3g}, p = {anova['p']:.3g}."
        self.batch_note.setText(text)
        self.last = {"kind": "compare", "rows": rows, "groups": stats_, "anova": anova, "normalised": norm}

    # -- response surface -----------------------------------------------------
    def _surface_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.f1, self.f2, self.rs_metric = QComboBox(), QComboBox(), QComboBox()
        for combo, label in ((self.f1, "Factor 1"), (self.f2, "Factor 2"), (self.rs_metric, "Response")):
            combo.setAccessibleName(label)
            row.addWidget(QLabel(label))
            row.addWidget(combo, 1)
        fit = QPushButton("Fit")
        fit.clicked.connect(self.fit_surface)
        row.addWidget(fit)
        lay.addLayout(row)
        self.rs_note = QLabel("Factors are numeric process or geometry parameters of the Workspace samples "
                              "(plus bulk density). At least 7 runs at 3+ levels of each factor are needed.")
        self.rs_note.setWordWrap(True)
        self.rs_note.setObjectName("Hint")
        lay.addWidget(self.rs_note)
        self.rs_table = ResultTable(["Term", "Coefficient", "SE"])
        self.rs_plot = PlotCanvas()
        split = QHBoxLayout()
        split.addWidget(self.rs_table, 2)
        split.addWidget(self.rs_plot, 3)
        lay.addLayout(split, 1)
        return w

    def _factor_value(self, sample, key):
        if key == "bulk density":
            return sample.bulk_density_g_cm3
        for d in (sample.process, sample.geometry):
            if key in d and isinstance(d[key].get("value"), (int, float)):
                return float(d[key]["value"])
        return None

    def fit_surface(self) -> dict | None:
        k1, k2, metric = self.f1.currentData(), self.f2.currentData(), self.rs_metric.currentData()
        ws = self.session.workspace
        x1, x2, y = [], [], []
        for run in self.session.runs:
            exp = ws.experiment_for_run(run.key)
            s = ws.samples.get(exp.sample_id) if exp else ws.samples.get(run.sample)
            v = run.result.value(metric) if metric else None
            if s is None or v is None or not math.isfinite(v):
                continue
            a, b = self._factor_value(s, k1), self._factor_value(s, k2)
            if a is not None and b is not None:
                x1.append(a), x2.append(b), y.append(v)
        try:
            rs = X.response_surface(x1, x2, y, names=(k1 or "x1", k2 or "x2"))
        except ValueError as exc:
            self.rs_note.setText(str(exc))
            self.rs_table.fill([])
            self.rs_plot.show_message("Not enough runs for a response surface", self.session.theme)
            return None
        self.rs_table.fill([(t, rs["coefficients"][t], rs["se"][t]) for t in rs["coefficients"]])
        st = rs["stationary"]
        where = ("inside" if rs["stationary_inside"] else "outside (not a supported prediction)")
        self.rs_note.setText(f"R² = {rs['r2']:.4f}, adjusted {rs['adj_r2']:.4f}, {rs['dof']} residual d.o.f. "
                             + (f"Stationary point ({rs['stationary_kind']}) at {st[0]:.4g}, {st[1]:.4g} → "
                                f"{st[2]:.4g}, {where} the tested box." if st else "No stationary point."))
        fig = self.rs_plot.figure
        fig.clear()
        ax = fig.add_subplot(111)
        G1, G2, Z = rs["grid"]
        cs = ax.contourf(G1, G2, Z, levels=14, cmap="viridis")
        fig.colorbar(cs, ax=ax, label=metric)
        ax.scatter(x1, x2, c="white", edgecolors="black", s=30, label="runs")
        ax.set_xlabel(k1)
        ax.set_ylabel(k2)
        ax.set_title("Quadratic response surface (tested box only)")
        self.rs_plot.canvas.draw_idle()
        self.last = {"kind": "surface", "result": rs}
        return rs

    # -- sensitivity -----------------------------------------------------------
    def _sensitivity_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.eq_combo = QComboBox()
        self.eq_combo.setAccessibleName("Equation")
        for eq in sorted(E.REGISTRY.values(), key=lambda e: e.name):
            self.eq_combo.addItem(eq.name, eq.id)
        self.eq_combo.currentIndexChanged.connect(self.analyse_equation)
        row.addWidget(QLabel("Equation"))
        row.addWidget(self.eq_combo, 1)
        lay.addLayout(row)
        self.el_table = ResultTable(["Input", "Default value", "Unit", "Elasticity ∂ln y/∂ln x"])
        self.pi_label = QLabel()
        self.pi_label.setWordWrap(True)
        self.pi_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(QLabel("Elasticity: % change in the result per 1 % change in an input, at the default values."))
        lay.addWidget(self.el_table, 1)
        lay.addWidget(Card("Dimensional analysis (Buckingham π)"))
        lay.addWidget(self.pi_label)
        return w

    def analyse_equation(self) -> None:
        eq = E.get(self.eq_combo.currentData())
        values = {v.symbol: v.default for v in eq.inputs}
        el = X.elasticities(eq, values)
        self.el_table.fill([(v.symbol, v.default if not v.vector else str(v.default), v.unit,
                             el.get(v.symbol, float("nan"))) for v in eq.inputs])
        da = X.dimensional_analysis(eq)
        groups = "; ".join(g["expression"] for g in da["groups"]) or "none"
        excl = f" Excluded (unit depends on a fitted exponent, or a list): {', '.join(da['excluded'])}." if da["excluded"] else ""
        self.pi_label.setText(f"{len(da['variables'])} variables with SI dimensions, matrix rank {da['rank']}: "
                              f"{da['n_groups']} independent dimensionless group(s): {groups}.{excl}")
        self.last = {"kind": "sensitivity", "elasticities": el, "dimensions": da}

    # -- DOE -------------------------------------------------------------------
    def _doe_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Factors (name, low, high). The design gives settings to run; results are left blank."))
        self.factors = QTableWidget(3, 3)
        self.factors.setHorizontalHeaderLabels(["Factor", "Low", "High"])
        self.factors.setTabKeyNavigation(False)
        self.factors.setAccessibleName("DOE factors")
        self.factors.setMaximumHeight(140)
        lay.addWidget(self.factors)
        row = QHBoxLayout()
        self.doe_kind = QComboBox()
        self.doe_kind.addItems(list(X.DOE_KINDS))
        self.doe_kind.setAccessibleName("Design type")
        self.doe_runs = QSpinBox()
        self.doe_runs.setRange(2, 200)
        self.doe_runs.setValue(10)
        self.doe_runs.setPrefix("LHS runs ")
        self.doe_center = QSpinBox()
        self.doe_center.setRange(0, 10)
        self.doe_center.setPrefix("centre points ")
        make = QPushButton("Suggest design")
        make.clicked.connect(self.make_design)
        save = QPushButton("Save as CSV…")
        save.clicked.connect(lambda: self.save_design())
        for x in (self.doe_kind, self.doe_runs, self.doe_center, make, save):
            row.addWidget(x)
        lay.addLayout(row)
        self.doe_note = QLabel()
        self.doe_note.setWordWrap(True)
        self.doe_note.setObjectName("Hint")
        lay.addWidget(self.doe_note)
        self.doe_table = ResultTable(["Run"])
        lay.addWidget(self.doe_table, 1)
        self.design = None
        return w

    def make_design(self) -> dict | None:
        factors = {}
        try:
            for r in range(self.factors.rowCount()):
                name = _cell(self.factors, r, 0)
                if name:
                    factors[name] = (float(_cell(self.factors, r, 1).replace(",", ".")),
                                     float(_cell(self.factors, r, 2).replace(",", ".")))
            self.design = X.doe_design(factors, self.doe_kind.currentText(), runs=self.doe_runs.value(),
                                       center_points=self.doe_center.value())
        except ValueError as exc:
            self.doe_note.setText(f"Cannot build the design: {exc}")
            return None
        rows = self.design["runs"]
        headers = list(rows[0])
        self.doe_table.setColumnCount(len(headers))
        self.doe_table.setHorizontalHeaderLabels(headers)
        self.doe_table.fill([[("" if r[h] is None else r[h]) for h in headers] for r in rows])
        self.doe_note.setText(f"{len(rows)} runs, randomised order (seed {self.design['seed']}). {self.design['note']}")
        self.last = {"kind": "doe", "design": self.design}
        return self.design

    def save_design(self, path: str | None = None):
        if not self.design:
            return None
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self, "Save design", str(Path.home() / "design.csv"), "CSV (*.csv)")
        if not path:
            return None
        rows = self.design["runs"]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            for r in rows:
                writer.writerow({k: ("" if v is None else v) for k, v in r.items()})
        return path

    # -- report and verification ------------------------------------------------
    def write_report(self, path: str | None = None):
        from ...core import materials as MT
        from ...io import report as R
        if path is None:
            name = self.session.project_name.replace(" ", "_")
            start = self.session.settings.get("last_export_dir", str(Path.home()))
            path, _f = QFileDialog.getSaveFileName(self, "Write report", f"{start}/{name}_report.html", "HTML (*.html)")
        if not path:
            return None
        ws = self.session.workspace
        qc = {}
        for run in self.session.runs:
            exp = ws.experiment_for_run(run.key)
            qc[run.key] = MT.qc_flags(run.measurement.id, run.result, run.options, experiment=exp,
                                      sample=ws.samples.get(exp.sample_id) if exp else None)
        rep = R.build_report(project=self.session.project_name, author=self.session.author, runs=self.session.runs,
                             manual=self.session.manual, workspace=ws, validation=V.run_all(),
                             notebook=self.session.notebook, qc=qc)
        html_path = R.write_html(rep, Path(path).with_suffix(".html"))
        md_path = R.write_markdown(rep, Path(path).with_suffix(".md"))
        self.session.status.emit(f"Report written: {html_path.name} and {md_path.name}", "success")
        return html_path, md_path

    def verify_excel(self, path: str | None = None):
        if path is None:
            start = self.session.settings.get("last_export_dir", str(Path.home()))
            path, _f = QFileDialog.getOpenFileName(self, "Workbook to verify", start, "Excel (*.xlsx)")
        if not path:
            return None
        try:
            res = X.verify_excel_export(path, [(r.sample, r.measurement.name, r.result.metrics) for r in self.session.runs])
        except Exception as exc:                            # noqa: BLE001 - shown to the user
            self.session.status.emit(f"Could not read {Path(path).name}: {exc}", "error")
            return None
        if res["ok"]:
            self.session.status.emit(f"Workbook matches the session: {res['checked']} values checked.", "success")
        else:
            self.session.status.emit(f"{len(res['mismatches'])} of {res['checked']} values differ: "
                                     f"{res['mismatches'][0]}", "warning")
        return res

    # -- refresh -----------------------------------------------------------------
    def refresh(self) -> None:
        names = []
        for run in self.session.runs:
            for m in run.result.metrics:
                if m.name not in names:
                    names.append(m.name)
        for combo, items in ((self.metric_combo, names), (self.rs_metric, names)):
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for n in items:
                combo.addItem(n, n)
            i = combo.findData(cur)
            combo.setCurrentIndex(i if i >= 0 else 0)
            combo.blockSignals(False)
        cur = self.ref_combo.currentData()
        self.ref_combo.blockSignals(True)
        self.ref_combo.clear()
        self.ref_combo.addItem("(none)", "")
        for s in dict.fromkeys(r.sample for r in self.session.runs):
            self.ref_combo.addItem(s, s)
        i = self.ref_combo.findData(cur)
        self.ref_combo.setCurrentIndex(i if i >= 0 else 0)
        self.ref_combo.blockSignals(False)
        keys = ["bulk density"]
        for s in self.session.workspace.samples.values():
            for d in (s.process, s.geometry):
                keys += [k for k, v in d.items() if isinstance(v.get("value"), (int, float)) and k not in keys]
        for combo, default in ((self.f1, 0), (self.f2, 1)):
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for k in keys:
                combo.addItem(k, k)
            i = combo.findData(cur)
            combo.setCurrentIndex(i if i >= 0 else min(default, len(keys) - 1))
            combo.blockSignals(False)
        if names:
            self.compare()
        if self.eq_combo.count() and not self.el_table.rowCount():
            self.analyse_equation()
