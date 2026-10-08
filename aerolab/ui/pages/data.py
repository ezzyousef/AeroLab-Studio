"""Data page: bring files in, see what arrived, and analyse them in one click.

This is the "automatic" half of the app. Drop a folder of instrument files and the page
guesses the measurement from the column names, maps the columns, runs the analyser and
adds a Run — but every guess is shown and can be overridden before anything is committed.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...core import measurements as M
from ...io import readers as R
from ...io.readers import Dataset, ImportError_
from ..widgets import Card, DropZone, EmptyState, HLine, Pill, ResultTable
from .base import Page

__all__ = ["DataPage"]

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "resources" / "samples"


class DataPage(Page):
    title = "Data"
    subtitle = "Import instrument files, check the columns, then analyse."
    glyph = "▤"

    analysed = Signal()

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        self._build_actions()
        self._build_body()
        session.datasets_changed.connect(self.refresh)
        self.refresh()

    # -- chrome --------------------------------------------------------------
    def _build_actions(self) -> None:
        self.btn_samples = QPushButton("Load demo data")
        self.btn_samples.setToolTip("Load the bundled example datasets from the three papers")
        self.btn_samples.clicked.connect(self.load_samples)
        self.btn_import = QPushButton("Import files…")
        self.btn_import.setObjectName("Primary")
        self.btn_import.clicked.connect(self.choose_files)
        self.actions.addWidget(self.btn_samples)
        self.actions.addWidget(self.btn_import)

    def _build_body(self) -> None:
        self.drop = DropZone()
        self.drop.files_dropped.connect(self.import_paths)
        self.drop.clicked.connect(self.choose_files)
        self.content.addWidget(self.drop)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # left: the imported files
        left = Card("Imported datasets")
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.currentRowChanged.connect(self._on_select)
        left.body.addWidget(self.file_list, 1)
        row = QHBoxLayout()
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setObjectName("Danger")
        self.btn_remove.clicked.connect(self._remove_current)
        self.btn_clear = QPushButton("Clear all")
        self.btn_clear.clicked.connect(self.session.clear_datasets)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        left.body.addLayout(row)
        split.addWidget(left)

        # right: what we found and how we will read it
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)

        self.detail = Card("Preview", "Select a dataset to see its columns.")
        self.meta_label = QLabel()
        self.meta_label.setObjectName("Hint")
        self.meta_label.setWordWrap(True)
        self.detail.body.addWidget(self.meta_label)
        self.preview = QTableWidget(0, 0)
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setAlternatingRowColors(True)
        self.preview.verticalHeader().setDefaultSectionSize(25)
        self.preview.setMinimumHeight(190)
        self.detail.body.addWidget(self.preview, 1)
        right_layout.addWidget(self.detail, 1)

        self.mapping_card = Card("Analyse", "Pick the measurement; columns are matched by name.")
        pick = QHBoxLayout()
        pick.setSpacing(8)
        pick.addWidget(QLabel("Measurement"))
        self.measure_combo = QComboBox()
        self.measure_combo.setMinimumWidth(240)
        for m in M.MEASUREMENTS:
            self.measure_combo.addItem(f"{m.name}  ·  {m.category}", m.id)
        self.measure_combo.currentIndexChanged.connect(self._update_mapping)
        pick.addWidget(self.measure_combo, 1)
        self.confidence = Pill("—", "good")
        pick.addWidget(self.confidence)
        self.mapping_card.body.addLayout(pick)

        self.map_table = QTableWidget(0, 3)
        self.map_table.setHorizontalHeaderLabels(["Needs", "Column in file", "Unit"])
        self.map_table.verticalHeader().setVisible(False)
        self.map_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.map_table.horizontalHeader().setStretchLastSection(True)
        self.map_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.map_table.setMaximumHeight(150)
        self.mapping_card.body.addWidget(self.map_table)

        run_row = QHBoxLayout()
        self.btn_analyse = QPushButton("Analyse this dataset")
        self.btn_analyse.setObjectName("Primary")
        self.btn_analyse.clicked.connect(self.analyse_current)
        self.btn_analyse_all = QPushButton("Analyse all imported")
        self.btn_analyse_all.setToolTip("Guess the measurement for every dataset and run them all")
        self.btn_analyse_all.clicked.connect(self.analyse_all)
        run_row.addWidget(self.btn_analyse)
        run_row.addWidget(self.btn_analyse_all)
        run_row.addStretch(1)
        self.mapping_card.body.addLayout(run_row)
        right_layout.addWidget(self.mapping_card)

        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        self.content.addWidget(split, 1)

    # -- import --------------------------------------------------------------
    def choose_files(self) -> None:
        start = self.session.settings.get("last_import_dir", str(Path.home()))
        paths, _filter = QFileDialog.getOpenFileNames(self, "Import data", start,
                                                      R.file_filter())
        if paths:
            self.import_paths(paths)

    def import_paths(self, paths: list[str]) -> None:
        collected: list[Dataset] = []
        problems: list[str] = []
        expanded: list[str] = []
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                expanded += [str(f) for f in sorted(p.iterdir())
                             if f.suffix.lower() in R.SUPPORTED_SUFFIXES]
            else:
                expanded.append(raw)
        for raw in expanded:
            try:
                collected += R.read_any(raw)
            except ImportError_ as exc:
                problems.append(str(exc))
            except Exception as exc:                            # noqa: BLE001 - shown to the user
                problems.append(f"{Path(raw).name}: {exc}")
        if collected:
            self.session.settings["last_import_dir"] = str(Path(expanded[0]).parent)
            self.session.save_settings()
            self.session.add_datasets(collected)
        for problem in problems[:3]:
            self.session.status.emit(problem, "error")
        if not collected and not problems:
            self.session.status.emit("No readable data files in that selection.", "warning")

    def load_samples(self) -> None:
        files = sorted(SAMPLES_DIR.glob("*.csv"))
        if not files:
            self.session.status.emit(f"No demo data found in {SAMPLES_DIR}", "warning")
            return
        self.import_paths([str(f) for f in files])

    # -- selection -----------------------------------------------------------
    def refresh(self) -> None:
        row = self.file_list.currentRow()
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for ds in self.session.datasets:
            item = QListWidgetItem(f"{ds.name}\n{ds.n_cols} cols · {ds.n_rows} rows")
            item.setToolTip(ds.source or ds.name)
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)
        if self.session.datasets:
            self.file_list.setCurrentRow(min(max(row, 0), len(self.session.datasets) - 1))
        else:
            self._clear_detail()
        has = bool(self.session.datasets)
        for btn in (self.btn_remove, self.btn_clear, self.btn_analyse, self.btn_analyse_all):
            btn.setEnabled(has)

    def current_dataset(self) -> Dataset | None:
        row = self.file_list.currentRow()
        if 0 <= row < len(self.session.datasets):
            return self.session.datasets[row]
        return None

    def _remove_current(self) -> None:
        row = self.file_list.currentRow()
        if row >= 0:
            self.session.remove_dataset(row)

    def _on_select(self, _row: int) -> None:
        ds = self.current_dataset()
        if ds is None:
            self._clear_detail()
            return
        self.detail.set_title(f"Preview · {ds.name}")
        bits = [f"{ds.n_cols} columns", f"{ds.n_rows} rows"]
        if ds.meta.get("delimiter"):
            bits.append(f"delimiter {ds.meta['delimiter']!r}")
        if ds.meta.get("decimal") == ",":
            bits.append("European decimals")
        if ds.meta.get("sheet"):
            bits.append(f"sheet {ds.meta['sheet']}")
        if ds.meta.get("preamble"):
            bits.append(f"{len(ds.meta['preamble'])} header lines skipped")
        self.meta_label.setText(" · ".join(bits))

        self.preview.clear()
        self.preview.setColumnCount(ds.n_cols)
        self.preview.setHorizontalHeaderLabels(ds.labels())
        n = min(ds.n_rows, 40)
        self.preview.setRowCount(n)
        for c in range(ds.n_cols):
            col = ds.columns[c]
            text_col = ds.text_columns.get(ds.headers[c])
            for r in range(n):
                if text_col is not None and r < len(text_col):
                    text = text_col[r]
                else:
                    value = col[r] if r < col.size else float("nan")
                    text = "" if value != value else f"{value:.6g}"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.preview.setItem(r, c, item)
        self.preview.resizeColumnsToContents()

        self._guess_measurement(ds)
        self._update_mapping()

    def _clear_detail(self) -> None:
        self.detail.set_title("Preview")
        self.meta_label.setText("Nothing imported yet.")
        self.preview.clear()
        self.preview.setRowCount(0)
        self.preview.setColumnCount(0)
        self.map_table.setRowCount(0)
        self.confidence.setText("—")

    # -- measurement guessing ------------------------------------------------
    def _guess_measurement(self, ds: Dataset) -> None:
        scores = {m.id: _match_score(m, ds) + _name_score(m, ds.name)
                  for m in M.MEASUREMENTS}
        best_id = max(scores, key=lambda k: (scores[k], -_index_of(k)))
        self._last_score = scores[best_id]
        if self._last_score <= 0:
            return
        index = self.measure_combo.findData(best_id)
        if index >= 0:
            self.measure_combo.blockSignals(True)
            self.measure_combo.setCurrentIndex(index)
            self.measure_combo.blockSignals(False)

    def _update_mapping(self) -> None:
        ds = self.current_dataset()
        if ds is None:
            return
        m = M.get(self.measure_combo.currentData())
        mapping = m.match_columns(ds.headers)
        guessed = set(M.guessed_channels(m, ds.headers, mapping))
        self.map_table.setRowCount(len(m.channels))
        missing = 0
        for r, channel in enumerate(m.channels):
            index = mapping.get(channel.key)
            need = QTableWidgetItem(f"{channel.label} ({channel.unit})"
                                    if channel.unit else channel.label)
            if not channel.required:
                need.setText(need.text() + "  — optional")
            if channel.key in guessed:
                need.setText(need.text() + "  — guessed from column order, check")
                need.setToolTip("No header names this quantity, so the next unused column "
                                "was taken. Pick the right column before analysing.")
            self.map_table.setItem(r, 0, need)

            combo = QComboBox()
            combo.addItem("— not mapped —", None)
            for i, label in enumerate(ds.labels()):
                combo.addItem(label, i)
            combo.setCurrentIndex(0 if index is None else index + 1)
            combo.currentIndexChanged.connect(lambda _i: self._mapping_edited())
            self.map_table.setCellWidget(r, 1, combo)

            unit = ds.units[index] if index is not None and index < len(ds.units) else ""
            self.map_table.setItem(r, 2, QTableWidgetItem(unit or "—"))
            if channel.required and index is None:
                missing += 1
        self._set_confidence(missing, len(m.required_channels()), guessed=len(guessed))

    def _mapping_edited(self) -> None:
        ds = self.current_dataset()
        if ds is None:
            return
        m = M.get(self.measure_combo.currentData())
        missing = sum(1 for r, ch in enumerate(m.channels)
                      if ch.required and self._mapped_index(r) is None)
        self._set_confidence(missing, len(m.required_channels()))

    def _set_confidence(self, missing: int, needed: int, guessed: int = 0) -> None:
        if missing == 0 and guessed:
            self.confidence.setText(f"{guessed} column(s) guessed — check")
            self.confidence.setObjectName("PillWarn")
        elif missing == 0:
            self.confidence.setText("all columns matched")
            self.confidence.setObjectName("PillGood")
        elif missing < needed:
            self.confidence.setText(f"{missing} column(s) missing")
            self.confidence.setObjectName("PillWarn")
        else:
            self.confidence.setText("no columns matched")
            self.confidence.setObjectName("PillBad")
        self.confidence.style().unpolish(self.confidence)
        self.confidence.style().polish(self.confidence)
        self.btn_analyse.setEnabled(missing == 0)

    def _mapped_index(self, row: int) -> int | None:
        widget = self.map_table.cellWidget(row, 1)
        return widget.currentData() if widget is not None else None

    # -- analysis ------------------------------------------------------------
    def analyse_current(self) -> None:
        ds = self.current_dataset()
        if ds is None:
            return
        m = M.get(self.measure_combo.currentData())
        mapping = {ch.key: self._mapped_index(r) for r, ch in enumerate(m.channels)}
        self._run(ds, m, mapping)

    def analyse_all(self) -> None:
        added = 0
        skipped: list[str] = []
        for i, ds in enumerate(self.session.datasets):
            self.file_list.setCurrentRow(i)
            m = M.get(self.measure_combo.currentData())
            mapping = m.match_columns(ds.headers)
            # Only run what the headers clearly identify: a dataset whose measurement or
            # columns had to be guessed is left for the user to map by hand.
            if (getattr(self, "_last_score", 0.0) < 0.5
                    or any(mapping.get(ch.key) is None for ch in m.required_channels())
                    or M.guessed_channels(m, ds.headers, mapping)):
                skipped.append(ds.name)
                continue
            added += 1 if self._run(ds, m, mapping, quiet=True) else 0
        level = "success" if added and not skipped else "warning"
        text = f"Analysed {added} of {len(self.session.datasets)} dataset(s)"
        if skipped:
            text += (f"; {len(skipped)} need their columns checked by hand: "
                     + ", ".join(skipped[:4]) + (" …" if len(skipped) > 4 else ""))
        self.session.status.emit(text, level)
        if added:
            self.analysed.emit()

    def _run(self, ds: Dataset, measurement, mapping: dict, quiet: bool = False) -> bool:
        try:
            if measurement.kind == "table":
                rows = [{k: float(ds.columns[v][i]) for k, v in mapping.items() if v is not None}
                        for i in range(ds.n_rows)]
                names = _sample_names(ds, ds.n_rows)
                for name, result in zip(names, measurement.run_table(rows)):
                    self.session.add_run(name, measurement, result, dataset_name=ds.name,
                                         source=ds.source, mapping=dict(mapping))
            else:
                data, notes = M.prepare_data(measurement, ds.columns, ds.units, mapping)
                result = measurement.run(data)
                if notes:
                    result.meta["import_notes"] = notes
                self.session.add_run(ds.name, measurement, result, dataset_name=ds.name,
                                     source=ds.source, mapping=dict(mapping),
                                     options=measurement.defaults())
                if notes and not quiet:
                    self.session.status.emit(f"{ds.name}: " + "; ".join(notes), "info")
        except Exception as exc:                                # noqa: BLE001 - shown to the user
            self.session.status.emit(f"{ds.name}: {exc}", "error")
            return False
        if not quiet:
            self.session.status.emit(f"Analysed {ds.name} as {measurement.name}", "success")
            self.analysed.emit()
        return True


def _match_score(measurement, ds: Dataset) -> float:
    """How well a measurement's channels line up with a dataset's headers."""
    mapping = measurement.match_columns(ds.headers)
    required = measurement.required_channels()
    if not required:
        return 0.0
    total = 0.0
    for channel in required:
        index = mapping.get(channel.key)
        if index is None:
            return 0.0
        total += max(channel.matches(ds.headers[index]),
                     channel.matches(ds.label(index)))
    return total / len(required)


def _name_score(measurement, filename: str) -> float:
    """How strongly a file name points at a measurement.

    Whole words only: matching bare substrings makes DSC's "Tg" tag hit
    "tga_TPU_aerogel.csv", and a fatigue tag shared by two measurements let whichever
    came last in the registry win. Longer matches count for more than short ones.
    """
    words = set(re.split(r"[^a-z0-9]+", filename.lower())) - {""}
    if not words:
        return 0.0
    best = 0.0
    for candidate, weight in [(measurement.id, 1.2), *[(t, 1.0) for t in measurement.tags]]:
        parts = set(re.split(r"[^a-z0-9]+", candidate.lower())) - {""}
        if not parts:
            continue
        overlap = parts & words
        if overlap and overlap == parts:
            # every word of the tag is in the file name: a solid hit, scaled by length
            best = max(best, weight * (0.55 + 0.08 * min(len(candidate), 5)))
    return best


def _index_of(measurement_id: str) -> int:
    return next((i for i, m in enumerate(M.MEASUREMENTS) if m.id == measurement_id), 99)


def _sample_names(ds: Dataset, count: int) -> list[str]:
    for key in ("Sample", "sample", "Name", "ID", "Specimen"):
        if key in ds.text_columns:
            values = ds.text_columns[key]
            if len(values) >= count:
                return values[:count]
    return [f"{ds.name} row {i + 1}" for i in range(count)]
