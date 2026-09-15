"""Shared page scaffolding: a title, a subtitle, an action row and a content area."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..state import Session

__all__ = ["Page"]


class Page(QWidget):
    """Base class for every page.

    Subclasses fill `self.content` and may add buttons to `self.actions`. `refresh()` is
    called whenever the page becomes visible or the session changes.
    """

    navigate = Signal(str)          # ask the main window to switch page

    title = "Page"          # shown in the navigation rail
    heading = ""            # shown at the top of the page; defaults to `title`
    subtitle = ""
    glyph = "•"

    def __init__(self, session: Session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self._title = QLabel(self.heading or self.title)
        self._title.setObjectName("PageTitle")
        titles.addWidget(self._title)
        if self.subtitle:
            self._subtitle = QLabel(self.subtitle)
            self._subtitle.setObjectName("PageSubtitle")
            self._subtitle.setWordWrap(True)
            titles.addWidget(self._subtitle)
        else:
            self._subtitle = None
        head.addLayout(titles, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        root.addLayout(head)

        self.content = QVBoxLayout()
        self.content.setSpacing(14)
        root.addLayout(self.content, 1)

    def set_subtitle(self, text: str) -> None:
        if self._subtitle is not None:
            self._subtitle.setText(text)

    def refresh(self) -> None:
        """Re-read the session. Overridden by pages that show session data."""

    def on_theme_changed(self, theme: str) -> None:
        """Re-draw anything that is not styled by the global stylesheet (plots)."""
