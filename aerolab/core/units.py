"""A small, dependency-free unit system.

Only what a materials lab actually needs: a dimension for every quantity used by the
equation library, and exact conversion factors to one canonical SI unit per dimension.
Temperature needs an offset, so conversions are expressed as (factor, offset) pairs:

    value_in_canonical = value * factor + offset
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DIMENSIONS", "canonical_unit", "convert", "units_for", "dimension_of", "format_value"]


@dataclass(frozen=True)
class _U:
    factor: float
    offset: float = 0.0


# dimension -> {unit: conversion to the canonical (first) unit}
DIMENSIONS: dict[str, dict[str, _U]] = {
    "dimensionless": {"-": _U(1.0), "%": _U(0.01), "ppm": _U(1e-6)},
    "length": {
        "m": _U(1.0), "cm": _U(1e-2), "mm": _U(1e-3), "µm": _U(1e-6), "um": _U(1e-6),
        "nm": _U(1e-9), "Å": _U(1e-10), "in": _U(0.0254),
    },
    "area": {"m^2": _U(1.0), "cm^2": _U(1e-4), "mm^2": _U(1e-6), "µm^2": _U(1e-12)},
    "second_moment": {"m^4": _U(1.0), "cm^4": _U(1e-8), "mm^4": _U(1e-12), "µm^4": _U(1e-24)},
    "volume": {"m^3": _U(1.0), "cm^3": _U(1e-6), "mL": _U(1e-6), "L": _U(1e-3), "mm^3": _U(1e-9)},
    "mass": {"kg": _U(1.0), "g": _U(1e-3), "mg": _U(1e-6), "µg": _U(1e-9)},
    "density": {
        "g/cm^3": _U(1.0), "kg/m^3": _U(1e-3), "mg/cm^3": _U(1e-3), "g/mL": _U(1.0), "g/L": _U(1e-3),
    },
    "concentration": {"g/L": _U(1.0), "kg/m^3": _U(1.0), "g/mL": _U(1000.0), "wt%": _U(1.0), "phr": _U(1.0)},
    "stress": {
        "MPa": _U(1.0), "Pa": _U(1e-6), "kPa": _U(1e-3), "GPa": _U(1e3), "N/mm^2": _U(1.0),
        "psi": _U(0.00689476), "bar": _U(0.1),
    },
    "pressure": {"Pa": _U(1.0), "kPa": _U(1e3), "MPa": _U(1e6), "bar": _U(1e5), "atm": _U(101325.0),
                 "psi": _U(6894.76), "mbar": _U(100.0), "Torr": _U(133.322)},
    "force": {"N": _U(1.0), "mN": _U(1e-3), "kN": _U(1e3), "cN": _U(1e-2), "gf": _U(0.00980665)},
    "temperature": {"°C": _U(1.0), "K": _U(1.0, -273.15), "°F": _U(5.0 / 9.0, -32.0 * 5.0 / 9.0)},
    "temperature_interval": {"K": _U(1.0), "°C": _U(1.0)},
    "thermal_conductivity": {"W/(m·K)": _U(1.0), "mW/(m·K)": _U(1e-3), "W/(m·°C)": _U(1.0)},
    "thermal_diffusivity": {"m^2/s": _U(1.0), "mm^2/s": _U(1e-6), "cm^2/s": _U(1e-4)},
    "effusivity": {"W·s^0.5/(m^2·K)": _U(1.0)},
    "specific_heat": {"J/(kg·K)": _U(1.0), "J/(g·K)": _U(1e3), "kJ/(kg·K)": _U(1e3)},
    "enthalpy": {"J/g": _U(1.0), "kJ/kg": _U(1.0), "J/kg": _U(1e-3)},
    "thermal_resistance": {"m^2·K/W": _U(1.0), "clo": _U(0.155)},
    "specific_surface": {"m^2/g": _U(1.0), "cm^2/g": _U(1e-4), "m^2/kg": _U(1e-3)},
    "specific_volume": {"cm^3/g": _U(1.0), "mL/g": _U(1.0), "m^3/kg": _U(1e3)},
    "viscosity": {"Pa·s": _U(1.0), "mPa·s": _U(1e-3), "P": _U(0.1), "cP": _U(1e-3)},
    "modulus": {"Pa": _U(1.0), "kPa": _U(1e3), "MPa": _U(1e6), "GPa": _U(1e9)},
    "shear_rate": {"1/s": _U(1.0), "s^-1": _U(1.0)},
    "frequency": {"Hz": _U(1.0), "rad/s": _U(1.0 / 6.283185307179586), "1/s": _U(1.0)},
    "time": {"s": _U(1.0), "ms": _U(1e-3), "min": _U(60.0), "h": _U(3600.0), "day": _U(86400.0)},
    "velocity": {"m/s": _U(1.0), "mm/s": _U(1e-3), "m/min": _U(1.0 / 60.0), "cm/min": _U(1e-2 / 60.0)},
    "flow_rate": {"mL/h": _U(1.0), "mL/min": _U(60.0), "L/h": _U(1000.0), "m^3/s": _U(3.6e9)},
    "angle": {"deg": _U(1.0), "rad": _U(57.29577951308232)},
    "wavevector": {"1/nm": _U(1.0), "1/Å": _U(10.0), "nm^-1": _U(1.0)},
    "surface_tension": {"mN/m": _U(1.0), "N/m": _U(1e3), "dyn/cm": _U(1.0), "mJ/m^2": _U(1.0)},
    "cycles": {"cycles": _U(1.0), "reversals": _U(0.5)},
    "count_density": {"1/cm^3": _U(1.0), "1/m^3": _U(1e-6)},
}


def canonical_unit(dimension: str) -> str:
    """The unit every value of this dimension is converted to internally."""
    return next(iter(DIMENSIONS[dimension]))


def units_for(dimension: str) -> list[str]:
    return list(DIMENSIONS[dimension])


def dimension_of(unit: str) -> str | None:
    for dim, table in DIMENSIONS.items():
        if unit in table:
            return dim
    return None


def convert(value: float, from_unit: str, to_unit: str, dimension: str | None = None) -> float:
    """Convert between two units of the same dimension."""
    if from_unit == to_unit:
        return value
    dim = dimension or dimension_of(from_unit)
    if dim is None:
        raise KeyError(f"Unknown unit {from_unit!r}")
    table = DIMENSIONS[dim]
    if from_unit not in table or to_unit not in table:
        raise KeyError(f"Cannot convert {from_unit!r} -> {to_unit!r} within {dim!r}")
    src, dst = table[from_unit], table[to_unit]
    canonical = value * src.factor + src.offset
    return (canonical - dst.offset) / dst.factor


def format_value(value: float, digits: int = 4) -> str:
    """Human-friendly number formatting: fixed notation when sensible, otherwise scientific."""
    if value is None:
        return "—"
    try:
        av = abs(float(value))
    except (TypeError, ValueError):
        return str(value)
    if value != value:  # NaN
        return "NaN"
    if av == 0:
        return "0"
    if av >= 1e6 or av < 1e-3:
        return f"{value:.{digits}g}".replace("e+0", "e+").replace("e-0", "e-")
    return f"{value:.{digits}g}"
