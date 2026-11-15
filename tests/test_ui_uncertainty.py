"""Calculator: correlated inputs, the Monte Carlo check and their trip through save and export."""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def calc(qapp):
    from aerolab.core import equations as E
    from aerolab.ui.pages.calculator import CalculatorPage
    from aerolab.ui.state import Session

    page = CalculatorPage(Session())
    page._show_equation(E.get("relative_density"))
    for sym, value, sigma in (("rho_b", "0.15", "0.004"), ("rho_s", "1.116", "0.02")):
        v, _u, s = page._inputs[sym]
        v.setText(value)
        s.setText(sigma)
    qapp.processEvents()
    yield page
    page.deleteLater()


def _sigma(text):
    return float(text.split("±")[1].split()[0])


def test_correlation_changes_the_propagated_sigma(calc, qapp):
    independent = _sigma(calc.result_label.text())
    dialog = calc.edit_correlations()
    dialog.spins["rho_b|rho_s"].setValue(0.7)
    assert dialog.apply()
    qapp.processEvents()
    correlated = _sigma(calc.result_label.text())
    a, b, sa, sb = 0.15, 1.116, 0.004, 0.02
    expected = a / b * math.sqrt((sa / a) ** 2 + (sb / b) ** 2 - 2 * 0.7 * (sa / a) * (sb / b))
    assert correlated == pytest.approx(expected, rel=2e-2)       # display rounds to 2 digits
    assert correlated < independent
    assert "correlations" in calc.note.text()


def test_monte_carlo_panel_shows_a_distribution_and_is_kept(calc, qapp, tmp_path):
    calc.mc_draws.setValue(5000)
    calc.run_monte_carlo()
    assert calc.mc_plot.isVisibleTo(calc)
    assert "Monte Carlo" in calc.mc_note.text()
    assert calc._mc["n"] > 4000
    calc._keep()
    kept = calc.session.manual[-1]
    assert kept.monte_carlo["low"] < kept.value < kept.monte_carlo["high"]
    assert "Monte Carlo" in kept.uncertainty_method()

    # session round trip keeps correlations and the Monte Carlo summary
    path = calc.session.save_project(tmp_path / "unc.aerolab")
    from aerolab.ui.state import Session
    other = Session()
    other.load_project(path)
    assert other.manual[-1].monte_carlo["high"] == pytest.approx(kept.monte_carlo["high"])


def test_changing_an_input_discards_a_stale_monte_carlo_result(calc, qapp):
    calc.mc_draws.setValue(2000)
    calc.run_monte_carlo()
    assert calc._mc
    calc._inputs["rho_b"][0].setText("0.16")
    qapp.processEvents()
    assert not calc._mc and not calc.mc_plot.isVisibleTo(calc)


def test_impossible_correlations_are_refused_in_the_dialog(qapp):
    from aerolab.core import equations as E
    from aerolab.ui.pages.calculator import CalculatorPage
    from aerolab.ui.state import Session

    page = CalculatorPage(Session())
    page._show_equation(E.get("k_total"))
    for sym in ("k_solid", "k_gas", "k_rad"):
        page._inputs[sym][2].setText("0.3")
    qapp.processEvents()
    dialog = page.edit_correlations()
    dialog.spins["k_solid|k_gas"].setValue(0.9)
    dialog.spins["k_solid|k_rad"].setValue(0.9)
    dialog.spins["k_gas|k_rad"].setValue(-0.9)
    assert dialog.apply() is False
    assert "positive semi-definite" in dialog.error.text()
    assert page._correlations == {}
    dialog.reject()
    page.deleteLater()


def test_excel_calculations_sheet_records_the_method(tmp_path):
    import openpyxl
    from aerolab.io import excel as X
    from aerolab.ui.state import ManualCalc

    calc = ManualCalc("relative_density", "Relative density", {"rho_b": 0.15, "rho_s": 1.116}, 0.1344, "-",
                      uncertainty=0.003, input_uncertainties={"rho_b": 0.004, "rho_s": 0.02},
                      correlations={"rho_b|rho_s": 0.7},
                      monte_carlo={"mean": 0.1345, "sd": 0.003, "low": 0.128, "high": 0.140, "n": 5000, "seed": 0})
    report = X.ExcelReport(manual=[{"name": calc.name, "inputs": calc.input_text(), "value": calc.value,
                                    "unit": calc.unit, "uncertainty": calc.uncertainty,
                                    "method": calc.uncertainty_method()}])
    path = X.write_workbook(report, tmp_path / "unc.xlsx")
    ws = openpyxl.load_workbook(path)["Calculations"]
    assert ws.cell(4, 7).value == "Uncertainty method"
    assert "correlated" in ws.cell(5, 7).value and "Monte Carlo" in ws.cell(5, 7).value
    assert "r(rho_b,rho_s)=0.7" in ws.cell(5, 2).value
