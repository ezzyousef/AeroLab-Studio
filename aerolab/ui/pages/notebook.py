"""Scientific notebook: timestamped notes linked to samples, experiments and runs.

Entries are saved in the session file, included in the report, and undoable. A note is
plain text. It is never interpreted as a command or rendered as HTML.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from ..widgets import Card
from .base import Page

__all__ = ["NotebookPage"]


class NotebookPage(Page):
    title = "Notebook"
    subtitle = "Observations as you work, time-stamped and linked to the sample, experiment or run they concern."
    glyph = "¶"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        export = QPushButton("Export as Markdown…")
        export.clicked.connect(lambda: self.export_markdown())
        self.actions.addWidget(export)

        entry = Card("New entry")
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("What did you see, change or decide?")
        self.editor.setTabChangesFocus(True)
        self.editor.setAccessibleName("Notebook entry text")
        self.editor.setMaximumHeight(120)
        entry.body.addWidget(self.editor)
        row = QHBoxLayout()
        row.addWidget(QLabel("Link to"))
        self.link_combo = QComboBox()
        self.link_combo.setAccessibleName("Link the entry to")
        row.addWidget(self.link_combo, 1)
        self.btn_add = QPushButton("Add entry")
        self.btn_add.setObjectName("Primary")
        self.btn_add.setShortcut("Ctrl+Return")
        self.btn_add.setToolTip("Add entry (Ctrl+Enter)")
        self.btn_add.clicked.connect(self.add_entry)
        row.addWidget(self.btn_add)
        entry.body.addLayout(row)
        self.content.addWidget(entry)

        log = Card("Entries", "Newest last. Select one and press Delete to remove it (undo with Ctrl+Z).")
        self.entries = QListWidget()
        self.entries.setWordWrap(True)
        self.entries.setAccessibleName("Notebook entries")
        log.body.addWidget(self.entries, 1)
        rm = QPushButton("Remove selected")
        rm.setShortcut("Delete")
        rm.clicked.connect(self.remove_selected)
        log.body.addWidget(rm, 0, Qt.AlignRight)
        self.content.addWidget(log, 1)
        session.notebook_changed.connect(self.refresh)
        session.workspace_changed.connect(self._fill_links)
        session.runs_changed.connect(self._fill_links)
        self.refresh()

    def _fill_links(self) -> None:
        cur = self.link_combo.currentData()
        self.link_combo.clear()
        self.link_combo.addItem("(nothing)", "")
        ws = self.session.workspace
        for s in ws.samples.values():
            self.link_combo.addItem(f"Sample {s.sample_id}", f"sample:{s.sample_id}")
        for e in ws.experiments.values():
            self.link_combo.addItem(f"Experiment {e.experiment_id} ({e.measurement_id})", f"experiment:{e.experiment_id}")
        for r in self.session.runs:
            self.link_combo.addItem(f"Run {r.title}", f"run:{r.key}")
        i = self.link_combo.findData(cur)
        self.link_combo.setCurrentIndex(i if i >= 0 else 0)

    def refresh(self) -> None:
        self._fill_links()
        self.entries.clear()
        for n in self.session.notebook:
            links = f"   [{', '.join(n.links)}]" if n.links else ""
            who = f" · {n.author}" if n.author else ""
            item = QListWidgetItem(f"{n.time}{who}{links}\n{n.text}")
            self.entries.addItem(item)

    def add_entry(self):
        link = self.link_combo.currentData()
        entry = self.session.add_note(self.editor.toPlainText(), (link,) if link else ())
        if entry is not None:
            self.editor.clear()
            self.entries.scrollToBottom()
        return entry

    def remove_selected(self) -> None:
        row = self.entries.currentRow()
        if row >= 0:
            self.session.remove_note(row)

    def export_markdown(self, path: str | None = None):
        if path is None:
            start = self.session.settings.get("last_export_dir", str(Path.home()))
            path, _f = QFileDialog.getSaveFileName(self, "Export notebook", f"{start}/notebook.md", "Markdown (*.md)")
        if not path:
            return None
        lines = [f"# Notebook: {self.session.project_name}", ""]
        for n in self.session.notebook:
            lines.append(f"## {n.time}" + (f" ({n.author})" if n.author else ""))
            if n.links:
                lines.append(f"*Linked to: {', '.join(n.links)}*")
            lines += ["", n.text, ""]
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        return path
