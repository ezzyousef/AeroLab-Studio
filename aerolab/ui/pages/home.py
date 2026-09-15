"""Home: what is in the session, and the quickest way to do the next thing."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...core import equations as E, measurements as M, validation as V
from ..widgets import Card, HLine, MetricTile, Pill, ResultTable, scrollable
from .base import Page

__all__ = ["HomePage"]


class HomePage(Page):
    title = "Home"
    heading = "AeroLab Studio"
    subtitle = "Equations, measurements and publication figures for aerogel-fibre research."
    glyph = "⌂"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        # -- headline counts
        tiles = Card("This session")
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles = {
            "datasets": MetricTile("Datasets imported", "0"),
            "runs": MetricTile("Measurements analysed", "0"),
            "metrics": MetricTile("Results computed", "0"),
            "manual": MetricTile("Kept calculations", "0"),
        }
        for i, tile in enumerate(self.tiles.values()):
            grid.addWidget(tile, 0, i)
        tiles.body.addLayout(grid)
        layout.addWidget(tiles)

        # -- what the app can do
        library = Card("Library")
        lib_grid = QGridLayout()
        lib_grid.setSpacing(10)
        summary = V.summary()
        lib_grid.addWidget(MetricTile("Equations", str(len(E.REGISTRY))), 0, 0)
        lib_grid.addWidget(MetricTile("Measurements", str(len(M.MEASUREMENTS))), 0, 1)
        lib_grid.addWidget(MetricTile("Paper values reproduced",
                                      f"{summary['reproduced']}/{summary['total']}"), 0, 2)
        lib_grid.addWidget(MetricTile("Origin graphs defined",
                                      str(sum(len(m.plots) for m in M.MEASUREMENTS))), 0, 3)
        library.body.addLayout(lib_grid)
        note = QLabel(
            "Every equation is checked against a number printed in one of the three source "
            "papers, so a unit slip shows up before it reaches a figure. Two cases are "
            "recorded as disagreements with the papers rather than as failures — see the "
            "Validation page."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        library.body.addWidget(note)
        layout.addWidget(library)

        # -- next steps
        steps = Card("Start here")
        for glyph, title, hint, target, label in [
            ("▤", "Import instrument data", "CSV, Excel, tab-separated text — columns are "
             "matched to the measurement automatically.", "data", "Open Data"),
            ("ƒ", "Work an equation by hand", "59 equations with unit conversion and "
             "uncertainty propagation.", "calculator", "Open Calculator"),
            ("◴", "Analyse a measurement", "Stress–strain, fatigue, TGA, DSC, BET, rheology "
             "— each with its own graphs.", "measure", "Open Measurements"),
            ("↗", "Send figures to Origin", "Styled workbooks and graphs, or a LabTalk "
             "package if Origin is elsewhere.", "export", "Open Export"),
        ]:
            steps.body.addWidget(_step_row(glyph, title, hint, label,
                                           lambda t=target: self.navigate.emit(t)))
        layout.addWidget(steps)

        # -- recent activity
        self.recent = Card("Recent analyses")
        self.recent_table = ResultTable(["Time", "Sample", "Measurement", "Headline result"])
        self.recent_table.setMinimumHeight(150)
        self.recent.body.addWidget(self.recent_table)
        layout.addWidget(self.recent)
        layout.addStretch(1)

        self.content.addWidget(scrollable(host), 1)
        session.runs_changed.connect(self.refresh)
        session.datasets_changed.connect(self.refresh)
        session.manual_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        counts = self.session.counts()
        for key, tile in self.tiles.items():
            tile.set_value(str(counts.get(key, 0)))
        rows = []
        for run in reversed(self.session.runs[-12:]):
            headline = next((m for m in run.result.metrics
                             if m.value is not None and m.value == m.value), None)
            text = (f"{headline.name} = {headline.value:.4g} {headline.unit}".strip()
                    if headline else "—")
            rows.append((run.created, run.sample, run.measurement.name, text))
        self.recent_table.fill(rows)


def _step_row(glyph: str, title: str, hint: str, button: str, on_click) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.setSpacing(12)

    from ..widgets import icon_label
    layout.addWidget(icon_label(glyph, 16))
    texts = QVBoxLayout()
    texts.setSpacing(1)
    name = QLabel(title)
    name.setStyleSheet("font-weight: 600;")
    note = QLabel(hint)
    note.setObjectName("Hint")
    note.setWordWrap(True)
    texts.addWidget(name)
    texts.addWidget(note)
    layout.addLayout(texts, 1)

    btn = QPushButton(button)
    btn.clicked.connect(on_click)
    layout.addWidget(btn, 0, Qt.AlignVCenter)
    return row
