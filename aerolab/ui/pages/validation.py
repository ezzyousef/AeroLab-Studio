"""Validation page: the equation library checked against the papers it came from.

This is the trust feature. Every row recomputes a number printed in one of the three
source papers. Two rows are recorded as disagreements with the papers rather than as
failures, with the reasoning spelled out, because pretending they match would be worse
than saying so.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...core import validation as V
from ..widgets import Card, MetricTile, ResultTable, scrollable
from .base import Page

__all__ = ["ValidationPage"]


class ValidationPage(Page):
    title = "Validation"
    subtitle = "The equation library recomputing reference values from the source papers and textbook physics."
    glyph = "✓"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        self.btn_rerun = QPushButton("Re-run checks")
        self.btn_rerun.setObjectName("Primary")
        self.btn_rerun.clicked.connect(self.refresh)
        self.actions.addWidget(self.btn_rerun)

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        summary = Card("Summary")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.tiles = {
            "total": MetricTile("Cases", "0"),
            "reproduced": MetricTile("Printed values reproduced", "0"),
            "other": MetricTile("Other checks passed", "0"),
            "documented": MetricTile("Documented disagreements", "0"),
            "failed": MetricTile("Failed", "0"),
        }
        for tile in self.tiles.values():
            row.addWidget(tile)
        summary.body.addLayout(row)
        note = QLabel(
            "“Reproduced” means our equation returns the reference value within its tolerance. "
            "The Basis column says what that reference is: a number printed in the paper, a "
            "physics/textbook value, or our own recomputation where the paper prints none — only "
            "the first kind is an independent check. “Documented disagreement” means we could "
            "not reproduce the paper's number; the printed value is shown beside ours."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        summary.body.addWidget(note)
        layout.addWidget(summary)

        table_card = Card("Cases")
        self.table = ResultTable(["Case", "Computed", "Reference", "Paper prints", "Basis",
                                  "Rel. error", "Status", "Source / comment"])
        self.table.setMinimumHeight(420)
        table_card.body.addWidget(self.table, 1)
        layout.addWidget(table_card, 1)

        self.content.addWidget(scrollable(host), 1)
        self.refresh()

    def refresh(self) -> None:
        results = V.run_all()
        summary = V.summary()
        self.tiles["total"].set_value(str(summary["total"]))
        self.tiles["reproduced"].set_value(
            f"{summary['reproduced_printed']}/{summary['printed_total']}")
        self.tiles["other"].set_value(str(summary["reproduced"] - summary["reproduced_printed"]))
        self.tiles["documented"].set_value(str(summary["documented_discrepancies"]))
        self.tiles["failed"].set_value(str(summary["failed"]))

        rows = []
        for r in results:
            if not r.ok:
                status = "FAILED"
            elif r.case.expect_match:
                status = "reproduced"
            else:
                status = "documented"
            detail = r.case.source
            if getattr(r.case, "comment", ""):
                detail += " — " + r.case.comment
            printed = r.case.printed_value
            rows.append((r.case.name, r.value, r.case.expected,
                         printed if printed is not None else "—", r.case.basis,
                         r.rel_error, status, detail))
        self.table.fill(rows)

        # colour the status column so the eye finds the exceptions
        colours = {"reproduced": "#0B7A4B", "documented": "#9A6400", "FAILED": "#B3261E"}
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, 6)
            if item is not None and item.text() in colours:
                item.setForeground(QColor(colours[item.text()]))
                font = item.font()
                font.setBold(True)
                item.setFont(font)

        if summary["failed"]:
            self.session.status.emit(
                f"{summary['failed']} validation case(s) failed — the equation library "
                "disagrees with the papers somewhere.", "error")
