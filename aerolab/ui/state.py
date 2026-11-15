"""The session: imported datasets, analysed runs and manual calculations.

One object holds everything the app knows, and emits Qt signals when it changes. Pages
read from it and never from each other, so adding a page never means touching the others.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..core import measurements as M
from ..core import workspace as W
from ..core.curves import AnalysisResult
from ..core.measurements import Measurement
from ..io.readers import Dataset

__all__ = ["Run", "ManualCalc", "Session", "SETTINGS_PATH"]

SETTINGS_PATH = Path.home() / ".aerolab_studio" / "settings.json"
PROJECT_SUFFIX = ".aerolab"


@dataclass
class Run:
    """One analysed dataset."""
    run_id: int
    sample: str
    measurement: Measurement
    result: AnalysisResult
    dataset_name: str = ""
    source: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    mapping: dict[str, int | None] = field(default_factory=dict)
    created: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    # Persistent unique id (saved with the session). Two analyses of the same file as the
    # same measurement are different runs and must not share a workspace link (Codex
    # review, finding 7); run_id is only a display counter and is renumbered on load.
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def title(self) -> str:
        return f"{self.sample} · {self.measurement.name}"

    @property
    def key(self) -> str:
        """The id used to link this run to experiments, lineage and notebook entries."""
        return self.uid

    @property
    def legacy_key(self) -> str:
        """The 1.3.0-development link key ("dataset::measurement"), for migrating old links."""
        return f"{self.dataset_name or self.sample}::{self.measurement.id}"


@dataclass(frozen=True)
class NoteEntry:
    """One entry of the scientific notebook: free text, timestamped, linked to records."""
    time: str
    text: str
    author: str = ""
    links: tuple[str, ...] = ()           # "sample:S1", "run:<key>", "experiment:E1"


@dataclass
class ManualCalc:
    """One equation evaluated by hand in the Calculator."""
    equation_id: str
    name: str
    inputs: dict[str, float]
    value: float
    unit: str
    reference: str = ""
    uncertainty: float | None = None
    created: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    input_uncertainties: dict[str, float] = field(default_factory=dict)
    correlations: dict[str, float] = field(default_factory=dict)     # "a|b" -> Pearson r
    monte_carlo: dict[str, float] = field(default_factory=dict)      # mean, sd, low, high, n, seed

    def input_text(self) -> str:
        def one(k, v):
            s = f"{k}={_fmt(v)}"
            if k in self.input_uncertainties:
                s += f" ± {_fmt(self.input_uncertainties[k])}"
            return s
        text = ", ".join(one(k, v) for k, v in self.inputs.items())
        if self.correlations:
            text += "; " + ", ".join(f"r({k.replace('|', ',')})={r:g}" for k, r in self.correlations.items())
        return text

    def uncertainty_method(self) -> str:
        """How the ± was obtained, for the export: method, correlations and any MC check."""
        if self.uncertainty is None:
            return "no uncertainty entered"
        text = "first-order, correlated inputs" if self.correlations else "first-order, independent inputs"
        mc = self.monte_carlo
        if mc:
            text += (f"; Monte Carlo mean {mc.get('mean', float('nan')):.5g}, SD {mc.get('sd', float('nan')):.3g}, "
                     f"95 % {mc.get('low', float('nan')):.5g} – {mc.get('high', float('nan')):.5g} "
                     f"({int(mc.get('n', 0))} draws, seed {int(mc.get('seed', 0))})")
        return text


@dataclass(frozen=True)
class Snapshot:
    """What the session held at one moment, and the action that produced it.

    Datasets, runs and calculations are treated as immutable once created, so a snapshot
    only needs to remember which ones were present — it is a list of references, not a
    copy of the data, and stays cheap even with a hundred thousand data points loaded.
    """
    label: str
    datasets: tuple
    runs: tuple
    manual: tuple
    next_run_id: int
    workspace: object = None              # a Workspace; replaced (never mutated) on every edit
    notebook: tuple = ()


HISTORY_LIMIT = 50


class Session(QObject):
    """Everything in flight, plus signals so the UI can follow along."""

    datasets_changed = Signal()
    runs_changed = Signal()
    manual_changed = Signal()
    theme_changed = Signal(str)
    status = Signal(str, str)          # message, level: info | success | warning | error
    busy = Signal(bool, str)
    history_changed = Signal()
    workspace_changed = Signal()
    notebook_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.datasets: list[Dataset] = []
        self.runs: list[Run] = []
        self.manual: list[ManualCalc] = []
        self.project_name: str = "Untitled session"
        self.author: str = ""
        self.settings: dict[str, Any] = self._load_settings()
        self.workspace: W.Workspace = W.Workspace()
        self.workspace.actor = self.author
        self.notebook: list[NoteEntry] = []
        self._next_run_id = 1
        self._history: list[Snapshot] = [self._snapshot("Empty session")]
        self._history_index = 0
        self._restoring = False

    # -- undo / redo ---------------------------------------------------------
    def _snapshot(self, label: str) -> Snapshot:
        return Snapshot(label, tuple(self.datasets), tuple(self.runs), tuple(self.manual),
                        self._next_run_id, self.workspace, tuple(self.notebook))

    def _record(self, label: str) -> None:
        """Remember the state *after* an action, so undo steps back to before it."""
        if self._restoring:
            return
        del self._history[self._history_index + 1:]       # a new action clears the redo tail
        self._history.append(self._snapshot(label))
        if len(self._history) > HISTORY_LIMIT:
            self._history.pop(0)
        self._history_index = len(self._history) - 1
        self.history_changed.emit()

    def can_undo(self) -> bool:
        return self._history_index > 0

    def can_redo(self) -> bool:
        return self._history_index < len(self._history) - 1

    def undo_label(self) -> str:
        return self._history[self._history_index].label if self.can_undo() else ""

    def redo_label(self) -> str:
        return self._history[self._history_index + 1].label if self.can_redo() else ""

    def undo(self) -> bool:
        if not self.can_undo():
            self.status.emit("Nothing to undo.", "info")
            return False
        undone = self._history[self._history_index].label
        self._history_index -= 1
        self._restore(self._history[self._history_index])
        self.status.emit(f"Undid: {undone}", "info")
        return True

    def redo(self) -> bool:
        if not self.can_redo():
            self.status.emit("Nothing to redo.", "info")
            return False
        self._history_index += 1
        snapshot = self._history[self._history_index]
        self._restore(snapshot)
        self.status.emit(f"Redid: {snapshot.label}", "info")
        return True

    def _restore(self, snapshot: Snapshot) -> None:
        self._restoring = True
        try:
            datasets_differ = tuple(self.datasets) != snapshot.datasets
            runs_differ = tuple(self.runs) != snapshot.runs
            manual_differ = tuple(self.manual) != snapshot.manual
            workspace_differs = self.workspace is not snapshot.workspace
            notebook_differs = tuple(self.notebook) != snapshot.notebook
            self.datasets = list(snapshot.datasets)
            self.runs = list(snapshot.runs)
            self.manual = list(snapshot.manual)
            self._next_run_id = snapshot.next_run_id
            if snapshot.workspace is not None:
                self.workspace = snapshot.workspace
            self.notebook = list(snapshot.notebook)
            if workspace_differs:
                self.workspace_changed.emit()
            if notebook_differs:
                self.notebook_changed.emit()
            if datasets_differ:
                self.datasets_changed.emit()
            if runs_differ:
                self.runs_changed.emit()
            if manual_differ:
                self.manual_changed.emit()
        finally:
            self._restoring = False
        self.history_changed.emit()

    # -- settings ------------------------------------------------------------
    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {
            "theme": "light",
            "palette": "review",
            "figure_size": "screen",
            "export_dpi": "print",
            "author": "",
            "last_import_dir": str(Path.home()),
            "last_export_dir": str(Path.home()),
            "origin_visible": False,
            "origin_keep_open": False,
            "auto_analyse": True,
            "decimals": 4,
            "palette_v2": False,
        }

    def _load_settings(self) -> dict[str, Any]:
        values = self._defaults()
        try:
            stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                values.update({k: v for k, v in stored.items() if k in values})
                # 1.2: the house style moved to Figure Studio's "Review" palette. Settings saved
                # with the old default move with it once; a palette chosen on purpose stays.
                if not stored.get("palette_v2") and values.get("palette") == "publication":
                    values["palette"] = "review"
        except (OSError, ValueError):
            pass
        values["palette_v2"] = True
        self.author = values.get("author", "")
        return values

    def save_settings(self) -> None:
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError as exc:
            self.status.emit(f"Could not save settings: {exc}", "warning")

    def set_setting(self, key: str, value: Any) -> None:
        if self.settings.get(key) == value:
            return
        self.settings[key] = value
        self.save_settings()
        if key == "theme":
            self.theme_changed.emit(str(value))
        if key == "author":
            self.author = str(value)
            self.workspace.actor = self.author

    @property
    def theme(self) -> str:
        return str(self.settings.get("theme", "light"))

    @property
    def palette_name(self) -> str:
        return str(self.settings.get("palette", "review"))

    # -- datasets ------------------------------------------------------------
    def add_datasets(self, datasets: list[Dataset]) -> None:
        if not datasets:
            return
        self.datasets.extend(datasets)
        names = ", ".join(d.name for d in datasets[:3])
        extra = f" and {len(datasets) - 3} more" if len(datasets) > 3 else ""
        self._record(f"import {len(datasets)} dataset(s)")
        self.datasets_changed.emit()
        self.status.emit(f"Imported {names}{extra}", "success")

    def remove_dataset(self, index: int) -> None:
        if 0 <= index < len(self.datasets):
            name = self.datasets.pop(index).name
            self._record(f"remove dataset “{name}”")
            self.datasets_changed.emit()
            self.status.emit(f"Removed {name}", "info")

    def clear_datasets(self) -> None:
        if not self.datasets:
            return
        count = len(self.datasets)
        self.datasets = []
        self._record(f"clear {count} dataset(s)")
        self.datasets_changed.emit()

    # -- runs ----------------------------------------------------------------
    def add_run(self, sample: str, measurement: Measurement, result: AnalysisResult,
                record: bool = True, **kwargs: Any) -> Run:
        run = Run(self._next_run_id, sample, measurement, result, **kwargs)
        self._next_run_id += 1
        self.runs.append(run)
        if record:
            ws = self.workspace.copy()
            detail = f"from {Path(run.source).name}" if run.source else "from pasted or generated data"
            ws.log("run analysed", f"run:{run.key}", detail)
            self.workspace = ws
            self._record(f"analyse “{sample}” as {measurement.name}")
        self.runs_changed.emit()
        return run

    def remove_run(self, run_id: int) -> None:
        run = self.run_by_id(run_id)
        before = len(self.runs)
        self.runs = [r for r in self.runs if r.run_id != run_id]
        if len(self.runs) != before:
            self._record(f"remove run “{run.sample if run else run_id}”")
            self.runs_changed.emit()

    def clear_runs(self) -> None:
        if not self.runs:
            return
        count = len(self.runs)
        self.runs = []
        self._record(f"clear {count} run(s)")
        self.runs_changed.emit()

    def replace_run_result(self, run: Run, result: AnalysisResult, options: dict) -> None:
        """Re-running with new settings replaces the Run, so undo restores the old one."""
        index = self.runs.index(run)
        self.runs[index] = Run(run.run_id, run.sample, run.measurement, result,
                               run.dataset_name, run.source, options, run.mapping, run.created, run.uid)
        self._record(f"re-run “{run.sample}” with new settings")
        self.runs_changed.emit()

    def run_by_id(self, run_id: int) -> Run | None:
        return next((r for r in self.runs if r.run_id == run_id), None)

    # -- workspace -------------------------------------------------------------
    def edit_workspace(self, label: str, change) -> Any:
        """Apply `change(workspace)` to a copy; keep it only if it succeeds. Undoable.

        Copy-on-write keeps undo cheap and correct: snapshots hold the old Workspace
        object, which no later edit ever touches. Raises whatever `change` raises.
        """
        ws = self.workspace.copy()
        ws.actor = self.author
        result = change(ws)
        self.workspace = ws
        self._record(label)
        self.workspace_changed.emit()
        return result

    # -- notebook ----------------------------------------------------------------
    def add_note(self, text: str, links: tuple[str, ...] = ()) -> NoteEntry | None:
        text = (text or "").strip()
        if not text:
            return None
        entry = NoteEntry(datetime.now().isoformat(timespec="seconds"), text, self.author, tuple(links))
        self.notebook.append(entry)
        self._record("add a notebook entry")
        self.notebook_changed.emit()
        return entry

    def remove_note(self, index: int) -> None:
        if 0 <= index < len(self.notebook):
            self.notebook.pop(index)
            self._record("remove a notebook entry")
            self.notebook_changed.emit()

    # -- manual calculations -------------------------------------------------
    def add_manual(self, calc: ManualCalc) -> None:
        self.manual.append(calc)
        self._record(f"keep “{calc.name}”")
        self.manual_changed.emit()

    def clear_manual(self) -> None:
        if not self.manual:
            return
        count = len(self.manual)
        self.manual = []
        self._record(f"clear {count} kept calculation(s)")
        self.manual_changed.emit()

    # -- project save / load -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """A project file: the analysed curves and results, not the raw imports."""
        from .. import __version__
        return {
            "format": "aerolab-session",
            "version": W.SCHEMA_VERSION,
            "schema_version": W.SCHEMA_VERSION,
            "app_version": __version__,
            "saved": datetime.now().isoformat(timespec="seconds"),
            "project": self.project_name,
            "author": self.author,
            "workspace": self.workspace.to_dict(),
            "notebook": [{"time": n.time, "text": n.text, "author": n.author, "links": list(n.links)}
                         for n in self.notebook],
            "runs": [
                {
                    "uid": r.uid,
                    "sample": r.sample,
                    "measurement": r.measurement.id,
                    "dataset": r.dataset_name,
                    "source": r.source,
                    "options": {k: _jsonable(v) for k, v in r.options.items()},
                    "mapping": {k: v for k, v in r.mapping.items()},
                    "metrics": [{"name": m.name, "value": _jsonable(m.value),
                                 "unit": m.unit, "note": m.note, "se": _jsonable(m.se)}
                                for m in r.result.metrics],
                    "curves": {k: [list(map(_jsonable, np.asarray(x, float).ravel())),
                                   list(map(_jsonable, np.asarray(y, float).ravel()))]
                               for k, (x, y) in r.result.curves.items()},
                }
                for r in self.runs
            ],
            "manual": [
                {"equation": c.equation_id, "name": c.name, "unit": c.unit,
                 "value": _jsonable(c.value), "inputs": {k: _jsonable(v) for k, v in c.inputs.items()},
                 "uncertainty": _jsonable(c.uncertainty),
                 "input_uncertainties": {k: _jsonable(v) for k, v in c.input_uncertainties.items()},
                 "correlations": {k: _jsonable(v) for k, v in c.correlations.items()},
                 "monte_carlo": {k: _jsonable(v) for k, v in c.monte_carlo.items()},
                 "reference": c.reference}
                for c in self.manual
            ],
        }

    def save_project(self, path: str | Path) -> Path:
        p = Path(path).with_suffix(PROJECT_SUFFIX)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
        self.project_name = p.stem
        self.status.emit(f"Session saved to {p.name}", "success")
        return p

    def load_project(self, path: str | Path) -> int:
        from ..core.curves import AnalysisResult as AR, Metric

        p = Path(path)
        payload = json.loads(p.read_text(encoding="utf-8"))
        if payload.get("format") != "aerolab-session":
            raise ValueError(f"{p.name} is not an AeroLab session file")
        return self.load_payload(payload, p.stem, p.name)

    def load_payload(self, payload: dict[str, Any], stem: str, display: str) -> int:
        """Replace the session with a saved one (already parsed). Older schemas are migrated."""
        from ..core.curves import AnalysisResult as AR, Metric

        payload, migration_notes = W.migrate(payload)
        self.runs = []
        self.manual = []
        loaded = 0
        for entry in payload.get("runs", []):
            try:
                measurement = M.get(entry["measurement"])
            except KeyError:
                continue
            metrics = [Metric(m["name"], _float(m.get("value")), m.get("unit", ""),
                              m.get("note", ""), None if m.get("se") is None else _float(m.get("se")))
                       for m in entry.get("metrics", [])]
            curves = {k: (np.asarray(v[0], dtype=float), np.asarray(v[1], dtype=float))
                      for k, v in entry.get("curves", {}).items() if len(v) == 2}
            result = AR(measurement.id, metrics, curves, {"measurement": measurement.id})
            mapping = {k: (int(v) if isinstance(v, (int, float)) else None)
                       for k, v in (entry.get("mapping") or {}).items()}
            extra = {"uid": str(entry["uid"])} if entry.get("uid") else {}
            self.add_run(entry.get("sample", "sample"), measurement, result, record=False,
                         dataset_name=entry.get("dataset", ""), source=entry.get("source", ""),
                         options=M.upgrade_options(measurement.id, entry.get("options", {})),
                         mapping=mapping, **extra)
            loaded += 1

        for entry in payload.get("manual", []):
            sigma = entry.get("uncertainty")
            self.manual.append(ManualCalc(
                entry.get("equation", ""), entry.get("name", ""),
                # list-valued inputs (a series of thicknesses, say) stay lists
                {k: ([_float(x) for x in v] if isinstance(v, list) else _float(v))
                 for k, v in entry.get("inputs", {}).items()},
                _float(entry.get("value")), entry.get("unit", ""), entry.get("reference", ""),
                uncertainty=None if sigma is None else _float(sigma),
                input_uncertainties={k: _float(v) for k, v in
                                     entry.get("input_uncertainties", {}).items()},
                correlations={k: _float(v) for k, v in entry.get("correlations", {}).items()},
                monte_carlo={k: _float(v) for k, v in entry.get("monte_carlo", {}).items()}))
        self.workspace = W.Workspace.from_dict(payload.get("workspace"))
        self.workspace.actor = self.author
        self._relink_legacy_runs(payload)
        self.notebook = [NoteEntry(str(n.get("time", "")), str(n.get("text", "")), str(n.get("author", "")),
                                   tuple(n.get("links", ()))) for n in payload.get("notebook", [])
                         if isinstance(n, dict)]
        self._record(f"open session “{stem}”")
        self.manual_changed.emit()
        self.workspace_changed.emit()
        self.notebook_changed.emit()

        self.project_name = payload.get("project") or stem
        self.author = payload.get("author", self.author)
        self.last_migration_notes = migration_notes
        extra = f" ({migration_notes[0]})" if migration_notes else ""
        self.status.emit(f"Loaded {loaded} run(s) from {display}{extra}", "success")
        return loaded

    def _relink_legacy_runs(self, payload: dict[str, Any]) -> None:
        """Files saved before runs had a uid linked them by "dataset::measurement".

        Such a link is moved to the new uid only when exactly one run has that legacy key;
        an ambiguous link is left as it was and recorded in the lineage instead of being
        guessed."""
        no_uid = [r for r, e in zip(self.runs, payload.get("runs", [])) if not e.get("uid")]
        if not no_uid:
            return
        by_legacy: dict[str, list[Run]] = {}
        for r in no_uid:
            by_legacy.setdefault(r.legacy_key, []).append(r)
        for exp in self.workspace.experiments.values():
            new_keys = []
            for k in exp.run_keys:
                runs = by_legacy.get(k, [])
                if len(runs) == 1:
                    new_keys.append(runs[0].uid)
                else:
                    new_keys.append(k)
                    if len(runs) > 1:
                        self.workspace.log("ambiguous run link kept", f"run:{k}",
                                           f"{len(runs)} runs share this legacy key; relink by hand")
            exp.run_keys = new_keys

    # -- portable archive --------------------------------------------------------
    def save_archive(self, path: str | Path) -> tuple[Path, list[str]]:
        """Session plus every attached file, in one verifiable zip (.aerolabz)."""
        from .. import __version__
        ws = self.workspace.copy()
        ws.log("archive exported", "session", Path(path).name)
        self.workspace = ws
        out, problems = W.export_archive(self.to_dict(), self.workspace, path, __version__)
        level = "warning" if problems else "success"
        self.status.emit(f"Archive written to {out.name}" + (f" — {len(problems)} file(s) left out"
                                                             if problems else ""), level)
        return out, problems

    def open_archive(self, path: str | Path, extract_to: str | Path | None = None) -> tuple[int, list[str]]:
        p = Path(path)
        dest = Path(extract_to) if extract_to else p.with_name(p.stem + "_attachments")
        payload, notes = W.import_archive(p, dest)
        loaded = self.load_payload(payload, p.stem, p.name)
        return loaded, notes

    # -- summary -------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        return {"datasets": len(self.datasets), "runs": len(self.runs),
                "manual": len(self.manual),
                "metrics": sum(len(r.result.metrics) for r in self.runs)}


def _fmt(value: Any) -> str:
    """Format one input for display — some equations take a list of values."""
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(f"{float(v):g}" for v in value) + "]"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _float(value: Any) -> float:
    try:
        return float(value) if value is not None else float("nan")
    except (TypeError, ValueError):
        return float("nan")
