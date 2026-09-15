"""Settings: appearance, figure defaults, Origin behaviour, and what is installed."""
from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ...io import origin as O
from ...viz import style as S
from ..widgets import Card, FieldRow, PlotCanvas, ResultTable, scrollable
from .base import Page

__all__ = ["SettingsPage"]


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Appearance, figure defaults and the environment this is running in."
    glyph = "⚙"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        # -- appearance
        appearance = Card("Appearance")
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["light", "dark"])
        self.theme_combo.setCurrentText(session.theme)
        self.theme_combo.currentTextChanged.connect(
            lambda v: session.set_setting("theme", v))
        appearance.body.addWidget(FieldRow(
            "Theme", self.theme_combo,
            help_text="Applies to the window and to every plot."))

        self.palette_combo = QComboBox()
        self.palette_combo.addItems(list(S.PALETTES))
        self.palette_combo.setCurrentText(session.palette_name)
        self.palette_combo.currentTextChanged.connect(self._palette_changed)
        appearance.body.addWidget(FieldRow(
            "Figure palette", self.palette_combo,
            help_text="“publication” is the Okabe–Ito colourblind-safe set; it is also what "
                      "is sent to Origin."))
        self.swatch = PlotCanvas(toolbar=False)
        self.swatch.setMinimumHeight(150)
        self.swatch.setMaximumHeight(190)
        appearance.body.addWidget(self.swatch)
        layout.addWidget(appearance)

        # -- figures
        figures = Card("Figure defaults")
        self.size_combo = QComboBox()
        self.size_combo.addItems(list(S.FIGURE_SIZES))
        self.size_combo.setCurrentText(session.settings.get("figure_size", "screen"))
        self.size_combo.currentTextChanged.connect(
            lambda v: session.set_setting("figure_size", v))
        figures.body.addWidget(FieldRow(
            "Export size", self.size_combo,
            help_text="single_column is 85 mm and double_column 175 mm, the two widths most "
                      "journals ask for."))
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(list(S.EXPORT_DPI))
        self.dpi_combo.setCurrentText(session.settings.get("export_dpi", "print"))
        self.dpi_combo.currentTextChanged.connect(
            lambda v: session.set_setting("export_dpi", v))
        figures.body.addWidget(FieldRow("Export resolution", self.dpi_combo,
                                        help_text="print = 300 dpi, poster = 600 dpi."))
        self.decimals = QSpinBox()
        self.decimals.setRange(2, 10)
        self.decimals.setValue(int(session.settings.get("decimals", 4)))
        self.decimals.valueChanged.connect(lambda v: session.set_setting("decimals", v))
        figures.body.addWidget(FieldRow("Significant figures shown", self.decimals))
        layout.addWidget(figures)

        # -- identity
        identity = Card("Report details")
        self.author_edit = QLineEdit(session.author)
        self.author_edit.setPlaceholderText("your name, for the export header")
        self.author_edit.editingFinished.connect(
            lambda: session.set_setting("author", self.author_edit.text().strip()))
        identity.body.addWidget(FieldRow("Author", self.author_edit))
        layout.addWidget(identity)

        # -- environment
        env = Card("Environment", "What this build can reach.")
        self.env_table = ResultTable(["Component", "Status"])
        self.env_table.setMaximumHeight(230)
        env.body.addWidget(self.env_table)
        refresh_row = QHBoxLayout()
        btn = QPushButton("Re-check")
        btn.clicked.connect(self._check_environment)
        refresh_row.addWidget(btn)
        refresh_row.addStretch(1)
        env.body.addLayout(refresh_row)
        layout.addWidget(env)
        layout.addStretch(1)

        self.content.addWidget(scrollable(host), 1)
        self._check_environment()
        self._draw_swatch()

    def _palette_changed(self, value: str) -> None:
        self.session.set_setting("palette", value)
        self._draw_swatch()

    def _draw_swatch(self) -> None:
        """Show the palette on a real plot rather than as coloured squares."""
        import numpy as np
        from ...core.curves import AnalysisResult
        from ...core.measurements import Plot, Series
        from ...viz import figures as F

        x = np.linspace(0, 10, 60)
        curves = {}
        series = []
        for i in range(6):
            curves[f"series {i + 1}"] = (x, np.sin(x + i * 0.55) + i * 0.75)
            series.append(Series(f"series {i + 1}", f"Sample {i + 1}", "scatter+line", "data"))
        plot = Plot("swatch", "Palette preview", "X", "", "Y", "", tuple(series))
        data = F.build_plot_data(plot, AnalysisResult("swatch", [], curves, {}),
                                 theme=self.session.theme,
                                 palette_name=self.palette_combo.currentText())
        self.swatch.show_plot(data, theme=self.session.theme)

    def _check_environment(self) -> None:
        rows = [("Python", sys.version.split()[0]),
                ("Platform", f"{platform.system()} {platform.release()}")]
        for module, label in [("PySide6", "PySide6 (interface)"), ("numpy", "NumPy"),
                              ("scipy", "SciPy"), ("matplotlib", "matplotlib"),
                              ("xlsxwriter", "xlsxwriter (Excel charts)"),
                              ("openpyxl", "openpyxl (Excel reading)")]:
            try:
                rows.append((label, __import__(module).__version__))
            except Exception:                                   # noqa: BLE001
                rows.append((label, "not installed"))
        ok, why = O.origin_available()
        rows.append(("OriginLab automation", "available" if ok else why))
        self.env_table.fill(rows)

    def on_theme_changed(self, theme: str) -> None:
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentText(theme)
        self.theme_combo.blockSignals(False)
        self._draw_swatch()
