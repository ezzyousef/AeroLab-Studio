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


def test_import_converts_units_and_refuses_the_wrong_quantity():
    import numpy as np
    from aerolab.core import measurements as M

    m = M.get("stress_strain")
    data, notes = M.prepare_data(m, [[0, 0.01], [0, 2000]], ["mm/mm", "kPa"],
                                 {"strain_pct": 0, "stress_mpa": 1})
    assert np.allclose(data["strain_pct"], [0, 1]) and np.allclose(data["stress_mpa"], [0, 2])
    assert len(notes) == 2
    with pytest.raises(ValueError, match="force"):
        M.prepare_data(m, [[0, 1], [0, 5]], ["%", "N"], {"strain_pct": 0, "stress_mpa": 1})
    data, _ = M.prepare_data(M.get("tga"), [[373.15], [100]], ["K", "%"],
                             {"temperature": 0, "weight_pct": 1})
    assert np.isclose(data["temperature"][0], 100.0)


def test_unnamed_columns_are_reported_as_guessed():
    from aerolab.core import measurements as M

    m = M.get("stress_strain")
    headers = ["Time", "Load", "Extension"]
    mapping = M.match_columns(m, headers)
    assert set(M.guessed_channels(m, headers, mapping)) == {"strain_pct", "stress_mpa"}
    headers = ["Strain", "Stress"]
    assert M.guessed_channels(m, headers, M.match_columns(m, headers)) == []


def test_old_dsc_option_name_still_applies():
    from aerolab.core import measurements as M

    assert M.upgrade_options("dsc", {"exo_up": True}) == {"endotherm_up": True}


def test_uncertainty_is_nan_not_zero_when_the_derivative_fails():
    def f(x):
        if x <= 0:
            raise ValueError("domain")
        return math.sqrt(x)

    eq = E.Equation("t_sqrt", "sqrt", "test", "", (E._V("x", "x", "-"),), E._V("y", "y", "-"), f)
    value, sigma = eq.compute_with_uncertainty({"x": 4.0}, {"x": 0.1})
    assert math.isclose(sigma, 0.1 / 4, rel_tol=1e-4)
    # next to the domain edge the one-sided difference still gives a number
    value, sigma = eq.compute_with_uncertainty({"x": 1e-9}, {"x": 1e-10})
    assert math.isfinite(sigma) and sigma > 0
    bad = E.Equation("t_bad", "bad", "test", "", (E._V("x", "x", "-"),), E._V("y", "y", "-"),
                     lambda x: 1.0 if x == 2.0 else float("nan"))
    assert math.isnan(bad.compute_with_uncertainty({"x": 2.0}, {"x": 0.1})[1])


# --------------------------------------------------------------------------- curve analyses
def test_dry_basis_tga_finds_its_loss_temperatures():
    from aerolab.core import curves as C

    r = C.analyze_tga([20, 100, 200, 300, 400], [100, 95, 90, 70, 50], dry_basis_at=100)
    got = {m.name: m.value for m in r.metrics}
    assert got["T at 5 % loss"] == pytest.approx(195.0)
    assert got["T at 10 % loss"] == pytest.approx(222.5)


def test_modulus_on_a_short_dense_curve_is_not_a_secant():
    import numpy as np
    from aerolab.core import curves as C

    e = np.linspace(0, 1, 10001)
    s = 100 * np.maximum(e - 0.02, 0)
    modulus, _r2, _window = C._auto_modulus(e, s, 5)
    assert modulus == pytest.approx(10000, rel=1e-6)


def test_bet_standard_error_includes_the_covariance():
    import numpy as np
    from aerolab.core import curves as C

    x = np.array([.05, .1, .15, .2, .25, .3])
    v = 1000 * x / ((1 - x) * (1 + 99 * x))
    v[2] *= 1.01
    vm = next(m for m in C.analyze_sorption_bet(x, v).metrics if m.name.startswith("Monolayer"))
    assert vm.se == pytest.approx(0.02813, rel=1e-3)
