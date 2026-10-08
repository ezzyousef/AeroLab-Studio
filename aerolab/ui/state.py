"""The session: imported datasets, analysed runs and manual calculations.

One object holds everything the app knows, and emits Qt signals when it changes. Pages
read from it and never from each other, so adding a page never means touching the others.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..core import measurements as M
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

    @property
    def title(self) -> str:
        return f"{self.sample} · {self.measurement.name}"


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

    def input_text(self) -> str:
        return ", ".join(f"{k}={_fmt(v)}" for k, v in self.inputs.items())


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

    def __init__(self) -> None:
        super().__init__()
        self.datasets: list[Dataset] = []
        self.runs: list[Run] = []
        self.manual: list[ManualCalc] = []
        self.project_name: str = "Untitled session"
        self.author: str = ""
        self.settings: dict[str, Any] = self._load_settings()
        self._next_run_id = 1
        self._history: list[Snapshot] = [self._snapshot("Empty session")]
        self._history_index = 0
        self._restoring = False

    # -- undo / redo ---------------------------------------------------------
    def _snapshot(self, label: str) -> Snapshot:
        return Snapshot(label, tuple(self.datasets), tuple(self.runs), tuple(self.manual),
                        self._next_run_id)

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
            self.datasets = list(snapshot.datasets)
            self.runs = list(snapshot.runs)
            self.manual = list(snapshot.manual)
            self._next_run_id = snapshot.next_run_id
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
            "palette": "publication",
            "figure_size": "screen",
            "export_dpi": "print",
            "author": "",
            "last_import_dir": str(Path.home()),
            "last_export_dir": str(Path.home()),
            "origin_visible": False,
            "origin_keep_open": False,
            "auto_analyse": True,
            "decimals": 4,
        }

    def _load_settings(self) -> dict[str, Any]:
        values = self._defaults()
        try:
            stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                values.update({k: v for k, v in stored.items() if k in values})
        except (OSError, ValueError):
            pass
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

    @property
    def theme(self) -> str:
        return str(self.settings.get("theme", "light"))

    @property
    def palette_name(self) -> str:
        return str(self.settings.get("palette", "publication"))

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
                               run.dataset_name, run.source, options, run.mapping, run.created)
        self._record(f"re-run “{run.sample}” with new settings")
        self.runs_changed.emit()

    def run_by_id(self, run_id: int) -> Run | None:
        return next((r for r in self.runs if r.run_id == run_id), None)

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
        return {
            "format": "aerolab-session",
            "version": 1,
            "saved": datetime.now().isoformat(timespec="seconds"),
            "project": self.project_name,
            "author": self.author,
            "runs": [
                {
                    "sample": r.sample,
                    "measurement": r.measurement.id,
                    "dataset": r.dataset_name,
                    "source": r.source,
                    "options": {k: _jsonable(v) for k, v in r.options.items()},
                    "metrics": [{"name": m.name, "value": _jsonable(m.value),
                                 "unit": m.unit, "note": m.note} for m in r.result.metrics],
                    "curves": {k: [list(map(_jsonable, np.asarray(x, float).ravel())),
                                   list(map(_jsonable, np.asarray(y, float).ravel()))]
                               for k, (x, y) in r.result.curves.items()},
                }
                for r in self.runs
            ],
            "manual": [
                {"equation": c.equation_id, "name": c.name, "unit": c.unit,
                 "value": _jsonable(c.value), "inputs": {k: _jsonable(v) for k, v in c.inputs.items()},
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

        self.runs = []
        self.manual = []
        loaded = 0
        for entry in payload.get("runs", []):
            try:
                measurement = M.get(entry["measurement"])
            except KeyError:
                continue
            metrics = [Metric(m["name"], _float(m.get("value")), m.get("unit", ""),
                              m.get("note", "")) for m in entry.get("metrics", [])]
            curves = {k: (np.asarray(v[0], dtype=float), np.asarray(v[1], dtype=float))
                      for k, v in entry.get("curves", {}).items() if len(v) == 2}
            result = AR(measurement.id, metrics, curves, {"measurement": measurement.id})
            self.add_run(entry.get("sample", "sample"), measurement, result, record=False,
                         dataset_name=entry.get("dataset", ""), source=entry.get("source", ""),
                         options=M.upgrade_options(measurement.id, entry.get("options", {})))
            loaded += 1

        for entry in payload.get("manual", []):
            self.manual.append(ManualCalc(
                entry.get("equation", ""), entry.get("name", ""),
                {k: _float(v) for k, v in entry.get("inputs", {}).items()},
                _float(entry.get("value")), entry.get("unit", ""), entry.get("reference", "")))
        self._record(f"open session “{p.stem}”")
        self.manual_changed.emit()

        self.project_name = payload.get("project") or p.stem
        self.author = payload.get("author", self.author)
        self.status.emit(f"Loaded {loaded} run(s) from {p.name}", "success")
        return loaded

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
