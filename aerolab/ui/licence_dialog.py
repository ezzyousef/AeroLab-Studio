"""The Licence dialog: edition and status, this computer's id, and offline activation.

Nothing here uses the network. "Copy activation request" puts a short text on the clipboard
for the user to send; "Install licence file…" verifies a file the publisher sent back.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout)

from .. import licensing as L
from .widgets import Card, HLine

__all__ = ["LicenceDialog"]


class LicenceDialog(QDialog):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Licence")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        card = Card("AeroLab Studio licence")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        self.edition_label = QLabel()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.warnings_label = QLabel()
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setObjectName("Hint")
        for w in (self.edition_label, self.status_label, self.warnings_label):
            w.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        self.device_field = QLineEdit(L.device_id())
        self.device_field.setReadOnly(True)
        self.device_field.setObjectName("Mono")
        self.device_field.setAccessibleName("This computer's device id")

        rows = [("Edition", self.edition_label), ("Status", self.status_label),
                ("Notes", self.warnings_label)]
        for r, (caption, widget) in enumerate(rows):
            key = QLabel(caption)
            key.setObjectName("TileLabel")
            key.setAlignment(Qt.AlignRight | Qt.AlignTop)
            grid.addWidget(key, r, 0)
            grid.addWidget(widget, r, 1)
        device_caption = QLabel("&Device id")
        device_caption.setObjectName("TileLabel")
        device_caption.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        device_caption.setBuddy(self.device_field)
        grid.addWidget(device_caption, len(rows), 0)
        grid.addWidget(self.device_field, len(rows), 1)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)

        note = QLabel("To license this computer, copy the activation request and send it to "
                      "the publisher, then install the licence file you receive. No data is "
                      "sent automatically.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        card.body.addWidget(HLine())
        card.body.addWidget(note)
        layout.addWidget(card)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.message_label.setAccessibleName("Result")
        layout.addWidget(self.message_label)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("&Copy activation request")
        self.copy_button.clicked.connect(self.copy_request)
        self.install_button = QPushButton("&Install licence file…")
        self.install_button.clicked.connect(self.choose_file)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("Primary")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.install_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.setTabOrder(self.device_field, self.copy_button)
        self.setTabOrder(self.copy_button, self.install_button)
        self.setTabOrder(self.install_button, self.close_button)
        self.refresh()

    # -- content -------------------------------------------------------------
    def refresh(self) -> None:
        st = L.status(self._store)
        if st.ok:
            name = st.claims.get("name") or st.claims.get("organisation") or ""
            edition = f"{st.edition.title()} ({st.claims.get('kind', '')})"
            sentence = "Licensed" + (f" to {name}" if name else "") + " on this computer."
        else:
            edition = "Free"
            sentence = st.reason or "No licence installed."
            if not L.ENFORCE:
                sentence += " Every feature is available in this version."
        self.edition_label.setText(edition)
        self.status_label.setText(sentence)
        self.warnings_label.setText("\n".join(st.warnings) if st.warnings else "None")

    # -- actions -------------------------------------------------------------
    def copy_request(self) -> None:
        QApplication.clipboard().setText(L.activation_request())
        self._say("Activation request copied to the clipboard.")

    def choose_file(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, "Install licence file", str(Path.home()),
                                               "Licence files (*.json *.lic);;All files (*)")
        if path:
            self.install_file(path)

    def install_file(self, path: str) -> bool:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            self._say("That file could not be read.", error=True)
            return False
        try:
            L.install(text, self._store)
        except L.LicenceError as exc:
            self._say(str(exc), error=True)
            return False
        self.refresh()
        self._say("Licence installed.")
        return True

    def _say(self, text: str, error: bool = False) -> None:
        self.message_label.setText(("Not installed: " if error else "") + text)
