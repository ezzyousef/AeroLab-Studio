"""Workspace page: samples, how they were made, the experiments run on them, and the lineage.

Every edit goes through `Session.edit_workspace`, so it is undoable and logged in the
chain of custody shown at the bottom right. Nothing here opens a modal dialog except the
file pickers, so the page can be driven headlessly.
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from ...core import measurements as M
from ...core import workspace as W
from ..widgets import Card, FieldRow, ResultTable
from .base import Page

__all__ = ["WorkspacePage"]

_COMPONENT_COLS = ["Component", "Mass fraction (0–1)", "Density (g/cm³)", "Supplier", "Lot"]
_KV_COLS = ["Parameter", "Value", "Unit or text"]
_HISTORY_COLS = ["Step", "Temperature (°C)", "Duration (min)", "Atmosphere / medium"]


def _num(text: str) -> float | None:
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    value = float(text)                      # ValueError is reported by the caller
    if not math.isfinite(value):
        raise ValueError(f"{text!r} is not a finite number")
    return value


def _editable_table(headers: list[str], rows: int = 0) -> QTableWidget:
    t = QTableWidget(rows, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setStretchLastSection(True)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setMinimumHeight(110)
    t.setTabKeyNavigation(False)             # Tab leaves the table (keyboard users)
    return t


def _cell(t: QTableWidget, r: int, c: int) -> str:
    item = t.item(r, c)
    return item.text().strip() if item else ""


def _set_row(t: QTableWidget, r: int, values) -> None:
    for c, v in enumerate(values):
        t.setItem(r, c, QTableWidgetItem("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))))


class WorkspacePage(Page):
    title = "Workspace"
    subtitle = ("Samples, composition, spinning and drying parameters, the experiments run on them, "
                "attached raw files and the full chain of custody.")
    glyph = "▦"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        self._current: str | None = None
        self._build()
        session.workspace_changed.connect(self.refresh)
        session.runs_changed.connect(self._refresh_run_choices)
        self.refresh()

    # -- layout --------------------------------------------------------------
    def _build(self) -> None:
        for label, slot, tip in (
                ("Save archive…", self.save_archive, "Session plus every attached file, verifiable by SHA-256"),
                ("Open archive…", self.open_archive, "Open a .aerolabz archive; attachments are checked"),
                ("Verify files", self.verify_files, "Check every attachment against its SHA-256")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            self.actions.addWidget(b)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # left: samples
        left = Card("Samples")
        self.sample_list = QListWidget()
        self.sample_list.setAccessibleName("Samples")
        self.sample_list.currentItemChanged.connect(self._on_pick)
        left.body.addWidget(self.sample_list, 1)
        row = QHBoxLayout()
        self.new_id = QLineEdit()
        self.new_id.setPlaceholderText("new sample id (optional)")
        self.new_id.setAccessibleName("New sample id")
        self.btn_new = QPushButton("New sample")
        self.btn_new.clicked.connect(lambda: self.new_sample(self.new_id.text().strip() or None))
        row.addWidget(self.new_id, 1)
        row.addWidget(self.btn_new)
        left.body.addLayout(row)
        row2 = QHBoxLayout()
        self.btn_rep = QPushButton("Add replicate")
        self.btn_rep.setToolTip("A new specimen with the same composition and process, grouped for statistics")
        self.btn_rep.clicked.connect(self.add_replicate)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self.remove_sample)
        row2.addWidget(self.btn_rep)
        row2.addWidget(self.btn_remove)
        left.body.addLayout(row2)
        left.setMinimumWidth(230)
        split.addWidget(left)

        # middle: the sample record
        mid = Card("Sample record", "Enter what you know; derived values show their formula.")
        self.f_name, self.f_batch, self.f_form = QLineEdit(), QLineEdit(), QLineEdit()
        self.f_rho_b, self.f_rho_b_sigma, self.f_rho_s = QLineEdit(), QLineEdit(), QLineEdit()
        for w, ph in ((self.f_rho_b, "g/cm³"), (self.f_rho_b_sigma, "± g/cm³"), (self.f_rho_s, "g/cm³ (blank: from components)")):
            w.setPlaceholderText(ph)
        mid.body.addWidget(FieldRow("Name", self.f_name))
        mid.body.addWidget(FieldRow("Batch", self.f_batch))
        mid.body.addWidget(FieldRow("Formulation", self.f_form))
        dens = QWidget()
        dl = QHBoxLayout(dens)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(self.f_rho_b, 2)
        dl.addWidget(self.f_rho_b_sigma, 1)
        dens.setFocusProxy(self.f_rho_b)
        self.f_rho_b.setAccessibleName("Bulk density")
        self.f_rho_b_sigma.setAccessibleName("Bulk density uncertainty")
        mid.body.addWidget(FieldRow("Bulk density ± σ", dens))
        mid.body.addWidget(FieldRow("Skeletal density", self.f_rho_s))

        self.tabs = QTabWidget()
        self.t_components = _editable_table(_COMPONENT_COLS)
        self.t_process = _editable_table(_KV_COLS)
        self.t_geometry = _editable_table(_KV_COLS)
        self.t_history = _editable_table(_HISTORY_COLS)
        self.f_notes = QPlainTextEdit()
        self.f_notes.setTabChangesFocus(True)
        for table, label in ((self.t_components, "Composition"), (self.t_process, "Production / spinning"),
                             (self.t_geometry, "Geometry"), (self.t_history, "Thermal history")):
            host = QWidget()
            hl = QVBoxLayout(host)
            hl.setContentsMargins(0, 6, 0, 0)
            hl.addWidget(table, 1)
            btns = QHBoxLayout()
            add, rm = QPushButton("Add row"), QPushButton("Remove row")
            add.clicked.connect(lambda _c=False, t=table: t.insertRow(t.rowCount()))
            rm.clicked.connect(lambda _c=False, t=table: t.removeRow(max(t.currentRow(), t.rowCount() - 1))
                               if t.rowCount() else None)
            btns.addWidget(add)
            btns.addWidget(rm)
            btns.addStretch(1)
            hl.addLayout(btns)
            table.setAccessibleName(label)
            self.tabs.addTab(host, label)
        self.tabs.addTab(self.f_notes, "Notes")
        mid.body.addWidget(self.tabs, 1)
        self.derived = QLabel()
        self.derived.setObjectName("Hint")
        self.derived.setWordWrap(True)
        self.derived.setTextInteractionFlags(Qt.TextSelectableByMouse)
        mid.body.addWidget(self.derived)
        self.form_error = QLabel()
        self.form_error.setObjectName("Hint")
        self.form_error.setWordWrap(True)
        mid.body.addWidget(self.form_error)
        self.btn_apply = QPushButton("Apply changes")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(self.apply_changes)
        mid.body.addWidget(self.btn_apply, 0, Qt.AlignRight)
        split.addWidget(mid)

        # right: experiments, attachments, lineage
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        exp = Card("Experiments", "One measurement on this sample, with the instrument and its calibration.")
        self.exp_table = ResultTable(["Id", "Measurement", "Instrument", "Calibrated", "Runs"])
        self.exp_table.setMinimumHeight(110)
        exp.body.addWidget(self.exp_table)
        self.e_measure = QComboBox()
        for m in M.MEASUREMENTS:
            self.e_measure.addItem(m.name, m.id)
        self.e_instrument, self.e_model, self.e_serial = QLineEdit(), QLineEdit(), QLineEdit()
        self.e_cal, self.e_operator = QLineEdit(), QLineEdit()
        self.e_cal.setPlaceholderText("YYYY-MM-DD")
        self.e_run = QComboBox()
        exp.body.addWidget(FieldRow("Measurement", self.e_measure))
        exp.body.addWidget(FieldRow("Instrument", self.e_instrument))
        exp.body.addWidget(FieldRow("Model / serial", _pair(self.e_model, self.e_serial)))
        exp.body.addWidget(FieldRow("Calibration date", self.e_cal))
        exp.body.addWidget(FieldRow("Operator", self.e_operator))
        exp.body.addWidget(FieldRow("Link analysed run", self.e_run))
        erow = QHBoxLayout()
        self.btn_exp = QPushButton("Add experiment")
        self.btn_exp.clicked.connect(self.add_experiment)
        self.btn_attach = QPushButton("Attach file…")
        self.btn_attach.setToolTip("Raw data, SEM/optical images or documents; recorded by SHA-256")
        self.btn_attach.clicked.connect(lambda: self.attach_files())
        erow.addWidget(self.btn_exp)
        erow.addWidget(self.btn_attach)
        erow.addStretch(1)
        exp.body.addLayout(erow)
        rl.addWidget(exp)

        att = Card("Attachments")
        self.att_table = ResultTable(["File", "Kind", "SHA-256", "Linked to", "Status"])
        self.att_table.setMinimumHeight(90)
        att.body.addWidget(self.att_table)
        rl.addWidget(att)

        lin = Card("Chain of custody", "Every change to this sample, its experiments, files and runs.")
        self.lineage = QListWidget()
        self.lineage.setAccessibleName("Chain of custody")
        lin.body.addWidget(self.lineage)
        rl.addWidget(lin, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 4)
        split.setStretchFactor(2, 4)
        self.content.addWidget(split, 1)
        self._status: dict[str, str] = {}

    # -- refresh -------------------------------------------------------------
    def refresh(self) -> None:
        ws = self.session.workspace
        current = self._current
        self.sample_list.blockSignals(True)
        self.sample_list.clear()
        for s in ws.samples.values():
            text = f"{'    ↳ ' if s.replicate_of else ''}{s.sample_id}" + (f" · {s.name}" if s.name else "")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, s.sample_id)
            self.sample_list.addItem(item)
        self.sample_list.blockSignals(False)
        ids = list(ws.samples)
        if current not in ids:
            current = ids[0] if ids else None
        self._current = current
        if current is not None:
            self.sample_list.setCurrentRow(ids.index(current))
        self._show_sample()
        self._refresh_run_choices()

    def _refresh_run_choices(self) -> None:
        self.e_run.clear()
        self.e_run.addItem("(none)", "")
        for run in self.session.runs:
            self.e_run.addItem(run.title, run.key)

    def _on_pick(self, item, _prev=None) -> None:
        if item is not None:
            self._current = item.data(Qt.UserRole)
            self._show_sample()

    def _show_sample(self) -> None:
        ws = self.session.workspace
        s = ws.samples.get(self._current) if self._current else None
        has = s is not None
        for w in (self.btn_rep, self.btn_remove, self.btn_apply, self.btn_exp, self.btn_attach, self.tabs):
            w.setEnabled(has)
        self.form_error.setText("")
        if not has:
            for w in (self.f_name, self.f_batch, self.f_form, self.f_rho_b, self.f_rho_b_sigma, self.f_rho_s):
                w.clear()
            for t in (self.t_components, self.t_process, self.t_geometry, self.t_history):
                t.setRowCount(0)
            self.derived.setText("Create a sample to record its composition, process and experiments.")
            self.exp_table.fill([])
            self.att_table.fill([])
            self.lineage.clear()
            for ev in ws.lineage[-30:]:
                self.lineage.addItem(f"{ev.time}  {ev.action}  {ev.target}  {ev.detail}")
            return
        self.f_name.setText(s.name)
        self.f_batch.setText(s.batch)
        self.f_form.setText(s.formulation)
        self.f_rho_b.setText("" if s.bulk_density_g_cm3 is None else f"{s.bulk_density_g_cm3:g}")
        self.f_rho_b_sigma.setText("" if s.bulk_density_sigma is None else f"{s.bulk_density_sigma:g}")
        self.f_rho_s.setText("" if s.skeletal_density_g_cm3 is None else f"{s.skeletal_density_g_cm3:g}")
        self.f_notes.setPlainText(s.notes)
        self.t_components.setRowCount(len(s.components))
        for r, c in enumerate(s.components):
            _set_row(self.t_components, r, [c.name, c.mass_fraction, c.density_g_cm3, c.supplier, c.lot])
        for table, mapping in ((self.t_process, s.process), (self.t_geometry, s.geometry)):
            table.setRowCount(len(mapping))
            for r, (k, v) in enumerate(mapping.items()):
                _set_row(table, r, [k, v.get("value", ""), v.get("unit", v.get("text", ""))])
        self.t_history.setRowCount(len(s.thermal_history))
        for r, step in enumerate(s.thermal_history):
            _set_row(self.t_history, r, [step.get("step", ""), step.get("temperature_c"),
                                         step.get("duration_min"), step.get("atmosphere", "")])
        try:
            derived = s.derived()
        except Exception as exc:                            # noqa: BLE001 - shown, not fatal
            derived = {}
            self.form_error.setText(f"Derived values unavailable: {exc}")
        lines = []
        for k, v in derived.items():
            sig = f" ± {v['sigma']:.3g}" if v.get("sigma") else ""
            lines.append(f"{k}: {v['value']:.5g}{sig} {v['unit']}  — {v['source']}")
        if s.replicate_of:
            lines.append(f"Replicate of {s.replicate_of} "
                         f"({len(ws.replicates(s.sample_id))} specimens in the group)")
        self.derived.setText("\n".join(lines) or "No derived values yet (enter densities or components).")

        exps = [e for e in ws.experiments.values() if e.sample_id == s.sample_id]
        self.exp_table.fill([(e.experiment_id, M.get(e.measurement_id).name if e.measurement_id in
                              {m.id for m in M.MEASUREMENTS} else e.measurement_id,
                              " ".join(x for x in (e.instrument.name, e.instrument.model) if x) or "—",
                              e.instrument.calibration_date or "not recorded", len(e.run_keys)) for e in exps])
        exp_ids = {e.experiment_id for e in exps}
        atts = [a for a in ws.attachments.values() if a.sample_id == s.sample_id or a.experiment_id in exp_ids]
        self.att_table.fill([(a.name, a.kind, a.sha256[:12] + "…", a.experiment_id or a.sample_id,
                              self._status.get(a.attachment_id, "not checked")) for a in atts])
        self.lineage.clear()
        for ev in ws.history(f"sample:{s.sample_id}"):
            who = f" ({ev.actor})" if ev.actor else ""
            self.lineage.addItem(f"{ev.time}{who}  {ev.action}  {ev.target}  {ev.detail}")

    # -- actions -------------------------------------------------------------
    def new_sample(self, sample_id: str | None = None) -> str | None:
        ws = self.session.workspace
        sid = sample_id or ws.new_id("S", ws.samples)
        try:
            self.session.edit_workspace(f"create sample {sid}", lambda w: w.add_sample(W.Sample(sid)))
        except W.WorkspaceError as exc:
            self.session.status.emit(str(exc), "error")
            return None
        self._current = sid
        self.new_id.clear()
        self.refresh()
        return sid

    def add_replicate(self) -> str | None:
        if not self._current:
            return None
        try:
            rep = self.session.edit_workspace(f"add a replicate of {self._current}",
                                              lambda w: w.add_replicate(self._current))
        except W.WorkspaceError as exc:
            self.session.status.emit(str(exc), "error")
            return None
        self._current = rep.sample_id
        self.refresh()
        return rep.sample_id

    def remove_sample(self) -> None:
        if not self._current:
            return
        sid = self._current
        try:
            self.session.edit_workspace(f"remove sample {sid}", lambda w: w.remove_sample(sid))
        except W.WorkspaceError as exc:
            self.session.status.emit(str(exc), "error")
            return
        self._current = None
        self.refresh()

    def _read_form(self) -> dict:
        components = []
        for r in range(self.t_components.rowCount()):
            name = _cell(self.t_components, r, 0)
            if not name and not _cell(self.t_components, r, 1):
                continue
            frac = _num(_cell(self.t_components, r, 1))
            if frac is None:
                raise ValueError(f"composition row {r + 1}: enter a mass fraction")
            components.append(W.Component(name or f"component {r + 1}", frac, _num(_cell(self.t_components, r, 2)),
                                          _cell(self.t_components, r, 3), _cell(self.t_components, r, 4)))

        def kv(table):
            out = {}
            for r in range(table.rowCount()):
                key = _cell(table, r, 0)
                if not key:
                    continue
                raw, unit = _cell(table, r, 1), _cell(table, r, 2)
                try:
                    out[key] = {"value": _num(raw), "unit": unit} if raw else {"text": unit}
                except ValueError:
                    out[key] = {"text": " ".join(x for x in (raw, unit) if x)}
            return out

        history = []
        for r in range(self.t_history.rowCount()):
            step = _cell(self.t_history, r, 0)
            if not step:
                continue
            history.append({"step": step, "temperature_c": _num(_cell(self.t_history, r, 1)),
                            "duration_min": _num(_cell(self.t_history, r, 2)),
                            "atmosphere": _cell(self.t_history, r, 3)})
        return dict(name=self.f_name.text().strip(), batch=self.f_batch.text().strip(),
                    formulation=self.f_form.text().strip(), components=components,
                    process=kv(self.t_process), geometry=kv(self.t_geometry), thermal_history=history,
                    bulk_density_g_cm3=_num(self.f_rho_b.text()),
                    bulk_density_sigma=_num(self.f_rho_b_sigma.text()),
                    skeletal_density_g_cm3=_num(self.f_rho_s.text()),
                    notes=self.f_notes.toPlainText())

    def apply_changes(self) -> bool:
        if not self._current:
            return False
        sid = self._current
        try:
            changes = self._read_form()
            self.session.edit_workspace(f"edit sample {sid}", lambda w: w.update_sample(sid, **changes))
        except (ValueError, W.WorkspaceError) as exc:
            self.form_error.setText(f"Not saved: {exc}")
            return False
        self.session.status.emit(f"Saved sample {sid}", "success")
        return True

    def add_experiment(self) -> str | None:
        if not self._current:
            return None
        sid = self._current
        ws = self.session.workspace
        eid = ws.new_id("E", ws.experiments)
        instrument = W.Instrument(self.e_instrument.text().strip(), self.e_model.text().strip(),
                                  self.e_serial.text().strip(), self.e_cal.text().strip())
        exp = W.Experiment(eid, sid, self.e_measure.currentData(), instrument, self.e_operator.text().strip())
        run_key = self.e_run.currentData()

        def change(w):
            w.add_experiment(exp)
            if run_key:
                w.link_run(eid, run_key)
        try:
            self.session.edit_workspace(f"add experiment {eid}", change)
        except W.WorkspaceError as exc:
            self.session.status.emit(str(exc), "error")
            return None
        return eid

    def attach_files(self, paths: list[str] | None = None) -> int:
        if not self._current:
            return 0
        if paths is None:
            start = self.session.settings.get("last_import_dir", str(Path.home()))
            paths, _f = QFileDialog.getOpenFileNames(self, "Attach files", start, "All files (*)")
        if not paths:
            return 0
        sid = self._current
        exps = [e.experiment_id for e in self.session.workspace.experiments.values() if e.sample_id == sid]
        target_exp = exps[-1] if exps else ""

        def change(w):
            for p in paths:
                w.attach_file(p, sample_id="" if target_exp else sid, experiment_id=target_exp)
        try:
            self.session.edit_workspace(f"attach {len(paths)} file(s)", change)
        except (W.WorkspaceError, OSError) as exc:
            self.session.status.emit(f"Could not attach: {exc}", "error")
            return 0
        return len(paths)

    def verify_files(self) -> dict[str, str]:
        holder: dict = {}

        def change(w):
            holder["r"] = w.verify_attachments()
        self.session.edit_workspace("verify attached files", change)
        self._status = {a.attachment_id: s for a, s in holder["r"]}
        bad = [a.name for a, s in holder["r"] if s != "ok"]
        if bad:
            self.session.status.emit(f"{len(bad)} attached file(s) missing or changed: {', '.join(bad[:3])}",
                                     "warning")
        else:
            self.session.status.emit(f"All {len(holder['r'])} attached file(s) match their SHA-256.", "success")
        self._show_sample()
        return dict(self._status)

    def save_archive(self, path: str | None = None):
        if path is None:
            start = self.session.settings.get("last_export_dir", str(Path.home()))
            name = self.session.project_name.replace(" ", "_")
            path, _f = QFileDialog.getSaveFileName(self, "Save archive", f"{start}/{name}{W.ARCHIVE_SUFFIX}",
                                                   f"AeroLab archive (*{W.ARCHIVE_SUFFIX})")
        if not path:
            return None
        try:
            return self.session.save_archive(path)
        except Exception as exc:                            # noqa: BLE001 - shown to the user
            self.session.status.emit(f"Could not write the archive: {exc}", "error")
            return None

    def open_archive(self, path: str | None = None, extract_to: str | None = None):
        if path is None:
            start = self.session.settings.get("last_export_dir", str(Path.home()))
            path, _f = QFileDialog.getOpenFileName(self, "Open archive", start,
                                                   f"AeroLab archive (*{W.ARCHIVE_SUFFIX});;All files (*)")
        if not path:
            return None
        try:
            loaded, notes = self.session.open_archive(path, extract_to)
        except Exception as exc:                            # noqa: BLE001 - shown to the user
            self.session.status.emit(f"Could not open the archive: {exc}", "error")
            return None
        if notes:
            self.session.status.emit("; ".join(notes[:2]), "warning")
        self.refresh()
        return loaded


def _pair(a: QWidget, b: QWidget) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(a)
    lay.addWidget(b)
    w.setFocusProxy(a)
    a.setAccessibleName("Instrument model")
    b.setAccessibleName("Instrument serial number")
    return w
