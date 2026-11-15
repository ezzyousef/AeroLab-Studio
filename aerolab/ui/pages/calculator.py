"""Calculator page: the manual half — every equation in the library, one at a time.

Pick an equation, type the inputs in whatever units you have, and the answer appears as
you type. Optional per-input uncertainties are propagated by central differences, and
every evaluation can be kept for the Excel export.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSpinBox, QSplitter, QTableWidget, QVBoxLayout, QWidget)

from ...core import equations as E
from ...core import uncertainty as UQ
from ...core.units import DIMENSIONS, convert, format_value, units_for
from ..state import ManualCalc
from ..widgets import Card, FieldRow, FormulaLabel, HLine, ResultTable, scrollable
from .base import Page

__all__ = ["CalculatorPage"]


class CalculatorPage(Page):
    title = "Calculator"
    subtitle = "Every equation from the three papers, evaluated by hand with unit conversion."
    glyph = "ƒ"

    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        self._inputs: dict[str, tuple[QLineEdit, QComboBox, QLineEdit]] = {}
        self._equation: E.Equation | None = None
        self._correlations: dict[str, float] = {}       # "a|b" -> r, for the current equation
        self._mc: dict[str, float] = {}                 # last Monte Carlo summary
        self._build()
        self._populate_list()
        if self.eq_list.count():
            self.eq_list.setCurrentRow(0)

    # -- chrome --------------------------------------------------------------
    def _build(self) -> None:
        self.btn_keep = QPushButton("Keep result")
        self.btn_keep.setToolTip("Add this evaluation to the session so it reaches the Excel export")
        self.btn_keep.clicked.connect(self._keep)
        self.btn_clear = QPushButton("Clear kept")
        self.btn_clear.clicked.connect(self.session.clear_manual)
        self.actions.addWidget(self.btn_clear)
        self.actions.addWidget(self.btn_keep)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # left: searchable equation list
        left = Card(f"{len(E.REGISTRY)} equations")
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search by name, symbol or tag…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._populate_list)
        left.body.addWidget(self.search)

        self.category = QComboBox()
        self.category.addItem("All categories", "")
        for cat in E.CATEGORIES:
            self.category.addItem(cat, cat)
        self.category.currentIndexChanged.connect(self._populate_list)
        left.body.addWidget(self.category)

        self.eq_list = QListWidget()
        self.eq_list.setWordWrap(True)
        self.eq_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.eq_list.currentItemChanged.connect(self._on_pick)
        left.body.addWidget(self.eq_list, 1)
        left.setMinimumWidth(268)
        split.addWidget(left)

        # right: the equation itself
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(14)

        self.detail = Card("Select an equation")
        self.formula = FormulaLabel()
        self.detail.body.addWidget(self.formula)
        self.reference = QLabel()
        self.reference.setObjectName("Hint")
        self.reference.setWordWrap(True)
        self.detail.body.addWidget(self.reference)
        self.detail.body.addWidget(HLine())

        self.fields_host = QWidget()
        self.fields = QVBoxLayout(self.fields_host)
        self.fields.setContentsMargins(0, 0, 0, 0)
        self.fields.setSpacing(9)
        self.detail.body.addWidget(scrollable(self.fields_host), 1)

        self.detail.body.addWidget(HLine())
        result_row = QHBoxLayout()
        result_row.setSpacing(9)
        self.result_label = QLabel("—")
        self.result_label.setObjectName("TileValue")
        self.result_unit_combo = QComboBox()
        self.result_unit_combo.setMinimumWidth(130)
        self.result_unit_combo.currentIndexChanged.connect(self._recompute)
        result_row.addWidget(QLabel("Result"))
        result_row.addWidget(self.result_label, 1)
        result_row.addWidget(self.result_unit_combo)
        self.detail.body.addLayout(result_row)
        self.note = QLabel()
        self.note.setObjectName("Hint")
        self.note.setWordWrap(True)
        self.detail.body.addWidget(self.note)

        unc_row = QHBoxLayout()
        unc_row.setSpacing(8)
        self.btn_corr = QPushButton("Correlations…")
        self.btn_corr.setToolTip("Optional: correlation coefficients between inputs that have a ±. "
                                 "Leave empty when the inputs were measured independently.")
        self.btn_corr.clicked.connect(self.edit_correlations)
        self.btn_mc = QPushButton("Monte Carlo check")
        self.btn_mc.setToolTip("Draw the inputs from their distributions and push them through the exact "
                               "equation, to see whether the first-order ± is trustworthy here.")
        self.btn_mc.clicked.connect(self.run_monte_carlo)
        self.mc_draws = QSpinBox()
        self.mc_draws.setRange(1000, 200000)
        self.mc_draws.setSingleStep(5000)
        self.mc_draws.setValue(20000)
        self.mc_draws.setSuffix(" draws")
        self.mc_draws.setAccessibleName("Monte Carlo draws")
        unc_row.addWidget(self.btn_corr)
        unc_row.addWidget(self.btn_mc)
        unc_row.addWidget(self.mc_draws)
        unc_row.addStretch(1)
        self.detail.body.addLayout(unc_row)
        self.mc_note = QLabel()
        self.mc_note.setObjectName("Hint")
        self.mc_note.setWordWrap(True)
        self.detail.body.addWidget(self.mc_note)
        from ..widgets import PlotCanvas
        self.mc_plot = PlotCanvas(toolbar=False)
        self.mc_plot.setMinimumHeight(190)
        self.mc_plot.setVisible(False)
        self.mc_plot.setAccessibleName("Monte Carlo distribution of the result")
        self.detail.body.addWidget(self.mc_plot)
        rl.addWidget(self.detail, 3)

        kept = Card("Kept results", "These are written to the Calculations sheet on export.")
        self.kept_table = ResultTable(["Equation", "Inputs", "Value", "± (1σ)", "Unit"])
        self.kept_table.setMaximumHeight(170)
        kept.body.addWidget(self.kept_table)
        rl.addWidget(kept, 1)

        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        self.content.addWidget(split, 1)

        self.session.manual_changed.connect(self._refresh_kept)
        self._refresh_kept()

    # -- list ----------------------------------------------------------------
    def _populate_list(self) -> None:
        query = self.search.text().strip()
        category = self.category.currentData()
        equations = E.search(query) if query else list(E.REGISTRY.values())
        if category:
            equations = [eq for eq in equations if eq.category == category]

        current = self._equation.id if self._equation else None
        self.eq_list.blockSignals(True)
        self.eq_list.clear()
        for eq in equations:
            item = QListWidgetItem(f"{eq.name}\n{eq.output.symbol} · {eq.category}")
            item.setData(Qt.UserRole, eq.id)
            item.setToolTip(eq.notes or eq.name)
            self.eq_list.addItem(item)
        self.eq_list.blockSignals(False)
        if not equations:
            return
        row = next((i for i in range(self.eq_list.count())
                    if self.eq_list.item(i).data(Qt.UserRole) == current), 0)
        self.eq_list.setCurrentRow(row)

    def _on_pick(self, item: QListWidgetItem | None, _prev=None) -> None:
        if item is None:
            return
        self._show_equation(E.get(item.data(Qt.UserRole)))

    # -- equation ------------------------------------------------------------
    def _show_equation(self, equation: E.Equation) -> None:
        self._equation = equation
        self._correlations = {}
        self._clear_mc()
        self.detail.set_title(equation.name)
        self.formula.set_formula(equation.latex, self.session.theme)
        bits = [equation.category]
        if equation.reference:
            bits.append(equation.reference)
        self.reference.setText("  ·  ".join(bits))

        while self.fields.count():
            item = self.fields.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._inputs.clear()

        for var in equation.inputs:
            value_edit = QLineEdit()
            default_text = _default_text(var)
            value_edit.setPlaceholderText(
                default_text or ("comma-separated values" if var.vector else "value"))
            value_edit.setText(default_text)
            value_edit.textChanged.connect(self._recompute)

            unit_combo = QComboBox()
            unit_combo.addItems(units_for(var.dimension) if var.dimension in DIMENSIONS
                                else [var.unit or "-"])
            if var.unit in [unit_combo.itemText(i) for i in range(unit_combo.count())]:
                unit_combo.setCurrentText(var.unit)
            unit_combo.currentIndexChanged.connect(self._recompute)

            sigma_edit = QLineEdit()
            sigma_edit.setPlaceholderText("± (optional)")
            sigma_edit.setMaximumWidth(110)
            sigma_edit.textChanged.connect(self._recompute)
            if var.vector:
                sigma_edit.setEnabled(False)       # no uncertainty on a list of values
                sigma_edit.setToolTip("Uncertainty propagation applies to single values only.")

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(value_edit, 3)
            row_layout.addWidget(unit_combo, 2)
            row_layout.addWidget(sigma_edit, 1)

            label = f"{var.label}  ({var.symbol})"
            # Built per equation, after the page-wide accessibility pass: name each part here.
            value_edit.setAccessibleName(f"{var.label} value")
            unit_combo.setAccessibleName(f"{var.label} unit")
            sigma_edit.setAccessibleName(f"{var.label} uncertainty")
            row.setFocusProxy(value_edit)          # the label's Alt+key lands on the value
            self.fields.addWidget(FieldRow(label, row, help_text=var.help))
            self._inputs[var.symbol] = (value_edit, unit_combo, sigma_edit)
        self.fields.addStretch(1)

        out = equation.output
        self.result_unit_combo.blockSignals(True)
        self.result_unit_combo.clear()
        self.result_unit_combo.addItems(units_for(out.dimension) if out.dimension in DIMENSIONS
                                        else [out.unit or "-"])
        if out.unit in [self.result_unit_combo.itemText(i)
                        for i in range(self.result_unit_combo.count())]:
            self.result_unit_combo.setCurrentText(out.unit)
        self.result_unit_combo.blockSignals(False)
        self._recompute()

    def _recompute(self) -> None:
        equation = self._equation
        if equation is None:
            return
        values: dict[str, float] = {}
        sigmas: dict[str, float] = {}
        for var in equation.inputs:
            value_edit, unit_combo, sigma_edit = self._inputs[var.symbol]
            text = value_edit.text().strip()
            if not text:
                self._set_result(None, f"Enter {var.label.lower()}.")
                return
            unit = unit_combo.currentText()

            if var.vector:
                parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
                try:
                    raw_list = [float(p) for p in parts]
                except ValueError:
                    self._set_result(None, f"{var.label}: '{text}' is not a list of numbers.")
                    return
                if not raw_list:
                    self._set_result(None, f"Enter at least one value for {var.label.lower()}.")
                    return
                values[var.symbol] = [_convert(v, unit, var) for v in raw_list]
                continue

            try:
                raw = float(text)
            except ValueError:
                self._set_result(None, f"{var.label}: '{text}' is not a number.")
                return
            values[var.symbol] = _convert(raw, unit, var)
            sigma_text = sigma_edit.text().strip()
            if sigma_text:
                try:
                    sigma_raw = abs(float(sigma_text))
                except ValueError:
                    self._set_result(None, f"{var.label}: uncertainty '{sigma_text}' is not a number.")
                    return
                # An uncertainty is a difference, so convert it as one: this scales °F to °C
                # by 5/9 without the 32° offset, and works the same for every other unit.
                sigmas[var.symbol] = abs(_convert(raw + sigma_raw, unit, var)
                                         - _convert(raw, unit, var))

        try:
            if sigmas and self._active_correlations(sigmas):
                lin = UQ.propagate_linear(equation, values, sigmas, self._active_correlations(sigmas))
                value, sigma = lin.value, lin.sigma
            elif sigmas:
                value, sigma = equation.compute_with_uncertainty(values, sigmas)
            else:
                value, sigma = float(equation.compute(**values)), None
        except Exception as exc:                                # noqa: BLE001 - shown to the user
            self._set_result(None, str(exc))
            return

        target = self.result_unit_combo.currentText()
        try:
            shown = convert(value, equation.output.unit, target, equation.output.dimension)
            shown_sigma = (abs(convert(value + sigma, equation.output.unit, target,
                                       equation.output.dimension) - shown)
                           if sigma is not None and math.isfinite(sigma) else sigma)
        except KeyError:
            shown, shown_sigma = value, sigma

        text = format_value(shown, self.session.settings.get("decimals", 4))
        if shown_sigma is not None and math.isfinite(shown_sigma):
            text += f"  ± {format_value(shown_sigma, 2)}"
        elif shown_sigma is not None:
            text += "  ± (uncertainty unavailable at this point)"
        corr = self._active_correlations(sigmas)
        note = equation.notes
        if corr:
            note = (note + "  " if note else "") + "± includes the correlations you entered."
        self._set_result(text, note)
        if getattr(self, "_last", None) and self._last[2:] != (dict(values), sigma, dict(sigmas)):
            self._clear_mc()                      # inputs changed: an old MC result no longer applies
        self._last = (value, equation.output.unit, dict(values), sigma, dict(sigmas))
        self.btn_mc.setEnabled(bool(sigmas))
        self.btn_corr.setEnabled(len(sigmas) >= 2)

    def _set_result(self, text: str | None, note: str = "") -> None:
        self.result_label.setText(text if text else "—")
        self.note.setText(note)
        self.btn_keep.setEnabled(bool(text))

    def _keep(self) -> None:
        equation = self._equation
        if equation is None or not getattr(self, "_last", None):
            return
        value, unit, inputs, sigma, sigmas = self._last
        self.session.add_manual(ManualCalc(equation.id, equation.name, inputs, value, unit,
                                           equation.reference, uncertainty=sigma,
                                           input_uncertainties=sigmas,
                                           correlations=self._active_correlations(sigmas),
                                           monte_carlo=dict(self._mc)))
        self.session.status.emit(f"Kept {equation.name}", "success")

    def _refresh_kept(self) -> None:
        self.kept_table.fill([(c.name, c.input_text(), c.value,
                               "—" if c.uncertainty is None else c.uncertainty, c.unit)
                              for c in self.session.manual])


    # -- correlated inputs and Monte Carlo --------------------------------------
    def _active_correlations(self, sigmas: dict) -> dict[str, float]:
        """Only pairs where both inputs currently carry a ±, and r is not zero."""
        return {k: r for k, r in self._correlations.items()
                if r and all(part in sigmas for part in k.split("|"))}

    def edit_correlations(self) -> QDialog | None:
        """A symmetric matrix of correlation coefficients between inputs with a ±."""
        last = getattr(self, "_last", None)
        if self._equation is None or not last or len(last[4]) < 2:
            self.session.status.emit("Enter a ± for at least two inputs first.", "info")
            return None
        names = list(last[4])
        dialog = QDialog(self)
        dialog.setWindowTitle("Input correlations")
        layout = QVBoxLayout(dialog)
        hint = QLabel("Pearson correlation between the errors of two inputs, from −1 to 1. Use it when "
                      "two inputs share a calibration or one was derived from the other; leave 0 "
                      "for independent measurements. Impossible combinations are refused.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        table = QTableWidget(len(names), len(names))
        table.setHorizontalHeaderLabels(names)
        table.setVerticalHeaderLabels(names)
        table.setAccessibleName("Correlation matrix")
        spins: dict[str, QDoubleSpinBox] = {}
        for i, a in enumerate(names):
            for j, b in enumerate(names):
                if j <= i:
                    label = QLabel("1" if i == j else "")
                    label.setAlignment(Qt.AlignCenter)
                    table.setCellWidget(i, j, label)
                    continue
                spin = QDoubleSpinBox()
                spin.setRange(-1.0, 1.0)
                spin.setDecimals(3)
                spin.setSingleStep(0.05)
                spin.setValue(self._correlations.get(f"{a}|{b}", self._correlations.get(f"{b}|{a}", 0.0)))
                spin.setAccessibleName(f"correlation of {a} with {b}")
                table.setCellWidget(i, j, spin)
                spins[f"{a}|{b}"] = spin
        layout.addWidget(table)
        error = QLabel()
        error.setObjectName("Hint")
        error.setWordWrap(True)
        layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        def accept():
            pairs = {k: s.value() for k, s in spins.items()}
            try:
                UQ.check_correlation(UQ.correlation_matrix(names, pairs), names)
            except ValueError as exc:
                error.setText(str(exc))
                return False
            self._correlations = {k: v for k, v in pairs.items() if v}
            dialog.accept()
            self._recompute()
            return True

        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.apply = accept                       # lets tests drive the dialog headlessly
        dialog.spins = spins
        dialog.error = error
        dialog.open()
        return dialog

    def run_monte_carlo(self) -> None:
        equation = self._equation
        last = getattr(self, "_last", None)
        if equation is None or not last or not last[4]:
            self.session.status.emit("Enter a ± for at least one input first.", "info")
            return
        value, unit, values, sigma, sigmas = last
        corr = self._active_correlations(sigmas)
        try:
            mc = UQ.monte_carlo(equation, values, sigmas, corr, n=int(self.mc_draws.value()), seed=0)
            lin = UQ.propagate_linear(equation, values, sigmas, corr)
        except Exception as exc:                            # noqa: BLE001 - shown to the user
            self._clear_mc()
            self.mc_note.setText(f"Monte Carlo could not run: {exc}")
            return
        verdict = UQ.compare(lin, mc)
        self._mc = {"mean": mc.mean, "sd": mc.sd, "median": mc.median, "low": mc.low, "high": mc.high,
                    "n": float(mc.n_used), "seed": float(mc.seed)}
        self.mc_note.setText(verdict["message"] + "  " + UQ.ASSUMPTIONS)
        from ...viz.figures import render_distribution
        render_distribution(mc.samples, nominal=value, sigma=sigma, low=mc.low, high=mc.high,
                            label=equation.output.label, unit=unit, theme=self.session.theme,
                            figure=self.mc_plot.figure)
        self.mc_plot.canvas.draw_idle()
        self.mc_plot.setVisible(True)

    def _clear_mc(self) -> None:
        self._mc = {}
        if hasattr(self, "mc_note"):
            self.mc_note.setText("")
            self.mc_plot.setVisible(False)

    def on_theme_changed(self, theme: str) -> None:
        if self._equation is not None:
            self.formula.set_formula(self._equation.latex, theme)


def _default_text(var) -> str:
    """The starting text for an input box, for scalars and for lists alike."""
    if var.default is None:
        return ""
    if isinstance(var.default, (list, tuple)):
        return ", ".join(f"{v:g}" for v in var.default)
    return f"{var.default:g}"


def _convert(value: float, unit: str, var) -> float:
    """Into the equation's own unit, leaving the value alone if we cannot."""
    if var.dimension not in DIMENSIONS:
        return value
    try:
        return convert(value, unit, var.unit, var.dimension)
    except KeyError:
        return value
