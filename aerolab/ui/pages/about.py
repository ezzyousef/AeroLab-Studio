"""About: who made this, what it is built on, and what it is built from."""
from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ... import __version__
from ...core import equations as E, measurements as M, validation as V
from ..widgets import Card, HLine, MetricTile, icon_label, scrollable
from .base import Page

__all__ = ["AboutPage"]

AUTHOR = "Ezzeldien Yousef"
EMAIL = "ezz.yousef@mail.utoronto.ca"
LAB = "MPML"
LAB_FULL = "Microcellular Plastics Manufacturing Laboratory"
DEPARTMENT = "Department of Mechanical & Industrial Engineering, University of Toronto"


class AboutPage(Page):
    title = "About"
    heading = "About AeroLab Studio"
    subtitle = "Who made it, what it does, and what it was built from."
    glyph = "ⓘ"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        layout.addWidget(self._identity_card())
        layout.addWidget(self._author_card())
        layout.addWidget(self._contents_card())
        layout.addWidget(self._sources_card())
        layout.addWidget(self._environment_card())
        layout.addStretch(1)

        self.content.addWidget(scrollable(host), 1)

    # -- cards ---------------------------------------------------------------
    def _identity_card(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(16)

        mark = QLabel()
        mark.setPixmap(_logo(76))
        mark.setFixedSize(84, 84)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet("background: transparent;")
        row.addWidget(mark, 0, Qt.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel("AeroLab Studio")
        name.setObjectName("PageTitle")
        version = QLabel(f"Version {__version__}")
        version.setObjectName("Hint")
        blurb = QLabel(
            "A desktop workbench for aerogel-fibre research: every equation and measurement "
            "from three papers on thermoplastic-polyurethane aerogels, applied by hand or "
            "automatically, with publication figures exported straight into OriginLab and a "
            "formatted Excel workbook.")
        blurb.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(version)
        text.addSpacing(6)
        text.addWidget(blurb)
        row.addLayout(text, 1)
        card.body.addLayout(row)
        return card

    def _author_card(self) -> Card:
        card = Card("Made by")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(7)

        rows = [
            ("Author", AUTHOR, None),
            ("Email", EMAIL, f"mailto:{EMAIL}"),
            ("Laboratory", f"{LAB} — {LAB_FULL}", None),
            ("Department", DEPARTMENT, None),
        ]
        self._links: list[tuple[QLabel, str, str]] = []
        for r, (label, value, link) in enumerate(rows):
            key = QLabel(label)
            key.setObjectName("TileLabel")
            key.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(key, r, 0)

            field = QLabel()
            if link:
                field.setOpenExternalLinks(False)
                field.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
                self._links.append((field, link, value))
            else:
                field.setText(value)
            field.setWordWrap(True)
            field.setTextInteractionFlags(Qt.TextBrowserInteraction)
            grid.addWidget(field, r, 1)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)
        self._paint_links(self.session.theme)

        buttons = QHBoxLayout()
        email_btn = QPushButton("Send an email")
        email_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(f"mailto:{EMAIL}?subject=AeroLab%20Studio")))
        copy_btn = QPushButton("Copy contact details")
        copy_btn.clicked.connect(self._copy_contact)
        buttons.addWidget(email_btn)
        buttons.addWidget(copy_btn)
        buttons.addStretch(1)
        card.body.addWidget(HLine())
        card.body.addLayout(buttons)
        return card

    def _contents_card(self) -> Card:
        card = Card("What is inside")
        grid = QGridLayout()
        grid.setSpacing(10)
        summary = V.summary()
        tiles = [
            ("Equations", str(len(E.REGISTRY))),
            ("Measurements", str(len(M.MEASUREMENTS))),
            ("Graphs defined", str(sum(len(m.plots) for m in M.MEASUREMENTS))),
            ("Paper values reproduced", f"{summary['reproduced']}/{summary['total']}"),
        ]
        for i, (label, value) in enumerate(tiles):
            grid.addWidget(MetricTile(label, value), 0, i)
        card.body.addLayout(grid)
        note = QLabel(
            "Every equation is checked against a number printed in one of the source papers, "
            "so a unit slip shows up before it can reach a figure. Two cases are recorded as "
            "disagreements with the papers rather than as failures — the Validation page "
            "explains both.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        card.body.addWidget(note)
        return card

    def _sources_card(self) -> Card:
        card = Card("Built from", "The three papers this program implements.")
        for citation in (
            "Omranpour, H. <i>et al.</i> (2024a) — Thermoplastic polyurethane aerogels: "
            "structure, porosity, fatigue and strain–life behaviour.",
            "Omranpour, H. <i>et al.</i> (2024b) — TPU/silica composite aerogels: thermal "
            "conductivity, cyclic recovery and insulation performance.",
            "Omranpour, H. <i>et al.</i> (2025) — Nanofibrous aerogel fibres: wet spinning, "
            "rheology, structure and thermal–mechanical properties.",
        ):
            label = QLabel("•  " + citation)
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            card.body.addWidget(label)
        return card

    def _environment_card(self) -> Card:
        card = Card("Running on")
        lines = [f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()}"]
        for module, label in (("PySide6", "PySide6"), ("numpy", "NumPy"), ("scipy", "SciPy"),
                              ("matplotlib", "matplotlib"), ("xlsxwriter", "XlsxWriter")):
            try:
                lines.append(f"{label} {__import__(module).__version__}")
            except Exception:                                   # noqa: BLE001
                lines.append(f"{label} — not installed")
        from ...io import origin as O
        ok, why = O.origin_available()
        text = QLabel("   ·   ".join(lines) + f"\n\nOriginLab automation: {why}")
        text.setObjectName("Hint")
        text.setWordWrap(True)
        card.body.addWidget(text)
        return card

    def _paint_links(self, theme: str) -> None:
        """Qt's default link blue is unreadable on the dark background, so set it here."""
        from .. import theme as T
        accent = T.colours(theme)["accent"]
        for field, href, text in getattr(self, "_links", ()):
            field.setText(f'<a href="{href}" style="color:{accent};text-decoration:none;">'
                          f'{text}</a>')

    def on_theme_changed(self, theme: str) -> None:
        self._paint_links(theme)

    def _copy_contact(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(
            f"{AUTHOR}\n{EMAIL}\n{LAB} — {LAB_FULL}\n{DEPARTMENT}")
        self.session.status.emit("Contact details copied to the clipboard", "success")


def _logo(size: int) -> QPixmap:
    """The application mark, drawn at the requested size."""
    from ..app import app_pixmap
    return app_pixmap(size)
