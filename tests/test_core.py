"""Units, equations and the validation cases."""
from __future__ import annotations

import math

import pytest

from aerolab.core import equations as E, units as U, validation as V


# --------------------------------------------------------------------------- units
def test_every_dimension_has_a_canonical_unit():
    for dimension, table in U.DIMENSIONS.items():
        assert table, f"{dimension} has no units"
        canonical = U.canonical_unit(dimension)
        assert table[canonical].factor == 1.0 and table[canonical].offset == 0.0, \
            f"{dimension}: the first unit {canonical!r} must be the identity"


@pytest.mark.parametrize("value,src,dst,expected", [
    (1.0, "g/cm^3", "kg/m^3", 1000.0),
    (25.0, "°C", "K", 298.15),
    (298.15, "K", "°C", 25.0),
    (32.0, "°F", "°C", 0.0),
    (1.0, "atm", "Pa", 101325.0),
    (1.0, "MPa", "psi", 145.0377),
    (26.0, "mW/(m·K)", "W/(m·K)", 0.026),
    (1.0, "m/min", "mm/s", 16.6667),
    (100.0, "cm^3/g", "m^3/kg", 0.1),
])
def test_conversions(value, src, dst, expected):
    assert U.convert(value, src, dst) == pytest.approx(expected, rel=1e-4)


def test_round_trip_every_unit():
    for dimension, table in U.DIMENSIONS.items():
        for unit in table:
            there = U.convert(7.5, U.canonical_unit(dimension), unit, dimension)
            back = U.convert(there, unit, U.canonical_unit(dimension), dimension)
            assert back == pytest.approx(7.5, rel=1e-9, abs=1e-9), f"{dimension}/{unit}"


def test_unknown_unit_raises():
    with pytest.raises(KeyError):
        U.convert(1.0, "furlong", "m")


# ----------------------------------------------------------------------- equations
def test_registry_is_consistent():
    assert len(E.REGISTRY) >= 59
    for key, equation in E.REGISTRY.items():
        assert key == equation.id
        assert equation.category in E.CATEGORIES
        assert equation.inputs, f"{key} has no inputs"
        assert equation.latex, f"{key} has no formula"
        symbols = [v.symbol for v in equation.inputs]
        assert len(symbols) == len(set(symbols)), f"{key} repeats an input symbol"
        for var in (*equation.inputs, equation.output):
            assert var.dimension in U.DIMENSIONS, f"{key}/{var.symbol}: {var.dimension}"
            if var.unit and var.unit != "-":
                assert var.unit in U.DIMENSIONS[var.dimension], \
                    f"{key}/{var.symbol}: {var.unit!r} is not a {var.dimension} unit"


def test_every_equation_runs_on_its_defaults():
    for key, equation in E.REGISTRY.items():
        values = {v.symbol: v.default for v in equation.inputs}
        assert all(v is not None for v in values.values()), f"{key} lacks a default"
        result = equation.compute(**values)
        assert result is not None, f"{key} returned None"
        assert math.isfinite(float(result)), f"{key} returned {result}"


def test_compute_rejects_wrong_arguments():
    equation = E.get("porosity_from_density")
    with pytest.raises(Exception):
        equation.compute(rho_b=0.2)                       # missing rho_s
    with pytest.raises(Exception):
        equation.compute(rho_b=0.2, rho_s=1.0, nonsense=1.0)


def test_uncertainty_propagates_sensibly():
    """Porosity = (1 - rb/rs)*100, so d(porosity)/d(rb) = -100/rs."""
    equation = E.get("porosity_from_density")
    value, sigma = equation.compute_with_uncertainty(
        {"rho_b": 0.211, "rho_s": 1.058}, {"rho_b": 0.002})
    assert value == pytest.approx(80.057, rel=1e-3)
    assert sigma == pytest.approx(100 * 0.002 / 1.058, rel=1e-3)


def test_uncertainty_is_zero_without_sigmas():
    equation = E.get("porosity_from_density")
    _value, sigma = equation.compute_with_uncertainty({"rho_b": 0.211, "rho_s": 1.058}, {})
    assert sigma == pytest.approx(0.0, abs=1e-12)


def test_search_finds_by_name_and_tag():
    assert any(e.id == "porosity_from_density" for e in E.search("porosity"))
    assert E.search("")                                    # empty query returns everything
    assert not E.search("zzzzzz")


# ---------------------------------------------------------------------- validation
def test_no_validation_case_fails():
    failures = [r.case.name for r in V.run_all() if not r.ok]
    assert not failures, f"the equation library disagrees with the papers: {failures}"


def test_validation_summary_adds_up():
    summary = V.summary()
    assert summary["total"] == len(V.CASES)
    assert summary["reproduced"] + summary["documented_discrepancies"] + summary["failed"] \
        == summary["total"]
    assert summary["failed"] == 0
    assert summary["documented_discrepancies"] == 2, \
        "the two known disagreements with the papers should still be recorded"


def test_documented_discrepancies_explain_themselves():
    for case in V.CASES:
        if not case.expect_match:
            assert case.comment, f"{case.name} disagrees with the paper but says nothing"
