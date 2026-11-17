"""Unit dimensionality audit.

A variable declared "dimensionless" is offered the units -, % and ppm in the Calculator,
and a pick of "%" silently multiplies the value by 0.01. So every quantity that has a
physical unit must declare that dimension, and every dimension must only hold units
that really are interchangeable.
"""
from __future__ import annotations

from fractions import Fraction

import pytest

from aerolab.core import equations as E, units as U


PHYSICAL = {
    # (equation, symbol): (dimension, unit)
    ("fibre_areal_density", "tex"): ("linear_density", "tex"),
    ("specific_strength", "sigma_spec"): ("specific_strength", "MPa·cm^3/g"),
    ("bending_rigidity", "EI"): ("bending_rigidity", "N·m^2"),
    ("diffusion_time", "D_diff"): ("diffusion_coefficient", "m^2/s"),
    ("herschel_bulkley", "K"): ("consistency", "Pa·s^n"),
    ("density_scaling_crosslinked", "K"): ("stress", "MPa"),
}


def _var(eq_id, symbol):
    eq = E.get(eq_id)
    for v in (*eq.inputs, eq.output):
        if v.symbol == symbol:
            return v
    raise KeyError(symbol)


@pytest.mark.parametrize("key", sorted(PHYSICAL))
def test_physical_quantities_declare_their_dimension(key):
    dimension, unit = PHYSICAL[key]
    var = _var(*key)
    assert (var.dimension, var.unit) == (dimension, unit)


def test_every_variable_unit_belongs_to_its_dimension():
    for eq in E.REGISTRY.values():
        for var in (*eq.inputs, eq.output):
            assert var.unit in U.DIMENSIONS[var.dimension], f"{eq.id}/{var.symbol}: {var.unit!r}"


def test_no_dimensionless_variable_hides_a_unit_in_its_help():
    for eq in E.REGISTRY.values():
        for var in (*eq.inputs, eq.output):
            if var.dimension != "dimensionless":
                continue
            for marker in ("m²", "m^2", "N·m", "MPa·", "per 1000 m", "Pa·s"):
                assert marker not in var.help, f"{eq.id}/{var.symbol} help names a unit: {var.help!r}"


@pytest.mark.parametrize("value,src,dst,expected", [
    (1.0, "tex", "dtex", 10.0),
    (9.0, "den", "tex", 1.0),                 # denier = g per 9000 m
    (1.0, "cN/tex", "MPa·cm^3/g", 10.0),       # 1 cN/tex = 10 kN·m/kg
    (1.0, "kN·m/kg", "MPa·cm^3/g", 1.0),
    (1.0, "N·m^2", "mN·mm^2", 1e9),
    (1.0, "cm^2/s", "m^2/s", 1e-4),
])
def test_new_dimensions_convert_exactly(value, src, dst, expected):
    assert U.convert(value, src, dst) == pytest.approx(expected, rel=1e-12)


def test_mass_fractions_are_not_a_mass_concentration():
    """wt% and phr are ratios of masses; g/L is mass per volume. They do not convert."""
    table = U.DIMENSIONS.get("concentration", {})
    for unit in ("wt%", "phr"):
        assert unit not in table


# ------------------------------------------------------------- SI base dimensions
def test_every_dimension_has_an_si_signature():
    for dimension in U.DIMENSIONS:
        assert dimension in U.SI_SIGNATURE, dimension


@pytest.mark.parametrize("dimension,expected", [
    ("thermal_conductivity", {"M": 1, "L": 1, "T": -3, "Θ": -1}),       # W/(m K)
    ("effusivity", {"M": 1, "T": Fraction(-5, 2), "Θ": -1}),            # W s^0.5/(m^2 K)
    ("thermal_resistance", {"M": -1, "T": 3, "Θ": 1}),                  # m^2 K/W
    ("surface_tension", {"M": 1, "T": -2}),
    ("specific_strength", {"L": 2, "T": -2}),
    ("bending_rigidity", {"M": 1, "L": 3, "T": -2}),
])
def test_si_signatures(dimension, expected):
    sig = U.SI_SIGNATURE[dimension]
    assert {k: v for k, v in sig.items() if v} == expected


def test_calculator_converts_a_diffusion_coefficient(qapp):
    """Before the audit, D_diff was 'dimensionless': picking cm²/s was impossible and % was offered."""
    from aerolab.ui.pages.calculator import _convert
    var = _var("diffusion_time", "D_diff")
    assert _convert(1.0, "cm^2/s", var) == pytest.approx(1e-4)
    assert "%" not in U.units_for(var.dimension)
