"""The equation library.

Every equation used in the three MPML aerogel-fibre papers, plus the standard
relations needed to work with them, expressed as data: symbol, unit, range, LaTeX,
source reference and a vectorised implementation (scalars or numpy arrays).

    >>> eq = REGISTRY["porosity_from_density"]
    >>> eq.compute(rho_b=0.211, rho_s=1.058)
    80.05...
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np

__all__ = ["Var", "Equation", "REGISTRY", "CATEGORIES", "by_category", "search", "get"]

SIGMA_SB = 5.670374419e-8  # Stefan-Boltzmann constant, W m^-2 K^-4
K_B = 1.380649e-23         # Boltzmann constant, J/K
K_AIR_STP = 26.0           # still air conductivity at ~25 C, mW/(m K)
MFP_AIR = 70.0             # mean free path of air at 1 atm, nm


@dataclass(frozen=True)
class Var:
    """One input or output of an equation."""

    symbol: str
    label: str
    unit: str
    dimension: str = "dimensionless"
    default: float | tuple[float, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    help: str = ""
    vector: bool = False          # takes a list of values rather than one

    @property
    def display(self) -> str:
        return f"{self.label} ({self.unit})" if self.unit not in ("", "-") else self.label


@dataclass(frozen=True)
class Equation:
    """A named, documented, vectorised formula."""

    id: str
    name: str
    category: str
    latex: str
    inputs: tuple[Var, ...]
    output: Var
    fn: Callable[..., float]
    reference: str = ""
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    # ------------------------------------------------------------------ compute
    def compute(self, **kwargs):
        missing = [v.symbol for v in self.inputs if v.symbol not in kwargs or kwargs[v.symbol] is None]
        if missing:
            raise ValueError(f"{self.id}: missing input(s) {', '.join(missing)}")
        extra = set(kwargs) - {v.symbol for v in self.inputs}
        if extra:
            raise ValueError(f"{self.id}: unexpected input(s) {', '.join(sorted(extra))}")
        return self.fn(**kwargs)

    def compute_with_uncertainty(self, values: dict[str, float], sigmas: dict[str, float]) -> tuple[float, float]:
        """First-order (linearised) propagation, treating the inputs as independent.

        Derivatives are central differences; next to a domain limit (a porosity of exactly
        1, a zero thickness) a one-sided difference is used instead. If the derivative cannot
        be evaluated at all the uncertainty is NaN -- reporting 0 would read as "exact".
        Correlated inputs, or σ large enough that the function curves noticeably over ±σ,
        are outside what this estimate covers.
        """
        base = float(self.compute(**values))
        var = 0.0
        for var_name, sigma in sigmas.items():
            if not sigma or var_name not in values:
                continue
            x = float(values[var_name])
            step = abs(x) * 1e-5 if x else 1e-8
            deriv = self._derivative(values, var_name, x, step, base)
            if not math.isfinite(deriv):
                return base, float("nan")
            var += (deriv * float(sigma)) ** 2
        return base, math.sqrt(var)

    def _derivative(self, values, name, x, step, base) -> float:
        def at(v):
            try:
                out = float(self.compute(**dict(values, **{name: v})))
            except Exception:  # noqa: BLE001 - outside the formula's domain
                return float("nan")
            return out if math.isfinite(out) else float("nan")

        hi, lo = at(x + step), at(x - step)
        if math.isfinite(hi) and math.isfinite(lo):
            return (hi - lo) / (2 * step)
        if math.isfinite(hi):
            return (hi - base) / step
        if math.isfinite(lo):
            return (base - lo) / step
        return float("nan")

    @property
    def input_symbols(self) -> tuple[str, ...]:
        return tuple(v.symbol for v in self.inputs)

    def describe(self) -> str:
        args = ", ".join(f"{v.symbol} [{v.unit}]" for v in self.inputs)
        return f"{self.name}: {self.output.symbol} = f({args})"


_REG: dict[str, Equation] = {}


def _add(eq: Equation) -> Equation:
    if eq.id in _REG:
        raise ValueError(f"duplicate equation id {eq.id}")
    _REG[eq.id] = eq
    return eq


def _V(symbol, label, unit, dimension="dimensionless", default=None, minimum=None, maximum=None,
       help="", vector=False) -> Var:
    return Var(symbol, label, unit, dimension, default, minimum, maximum, help, vector)


# =============================================================================
# 1. Structure, density and porosity
# =============================================================================
_add(Equation(
    id="porosity_from_density",
    name="Porosity from bulk and skeletal density",
    category="Structure & porosity",
    latex=r"\varepsilon = \left(1 - \frac{\rho_b}{\rho_s}\right)\times 100",
    inputs=(
        _V("rho_b", "Bulk (apparent) density", "g/cm^3", "density", 0.211, 0, None, "Mass divided by the envelope volume"),
        _V("rho_s", "Skeletal (solid) density", "g/cm^3", "density", 1.058, 1e-9, None, "Rule-of-mixtures density of the solid"),
    ),
    output=_V("epsilon", "Porosity", "%", "dimensionless"),
    fn=lambda rho_b, rho_s: (1.0 - np.asarray(rho_b, float) / np.asarray(rho_s, float)) * 100.0,
    reference="Omranpour et al. (2024a) Eq. 1; (2024b) Eq. 1; (2025) Eq. 2",
    notes="The papers write it as (1/ρb − 1/ρs)/(1/ρb), which is algebraically identical.",
    tags=("porosity", "density", "aerogel"),
))

_add(Equation(
    id="pore_volume",
    name="Specific pore volume",
    category="Structure & porosity",
    latex=r"V_p = \frac{1}{\rho_b} - \frac{1}{\rho_s}",
    inputs=(
        _V("rho_b", "Bulk density", "g/cm^3", "density", 0.211, 1e-9),
        _V("rho_s", "Skeletal density", "g/cm^3", "density", 1.058, 1e-9),
    ),
    output=_V("V_p", "Pore volume", "cm^3/g", "specific_volume"),
    fn=lambda rho_b, rho_s: 1.0 / np.asarray(rho_b, float) - 1.0 / np.asarray(rho_s, float),
    reference="Omranpour et al. (2024a) Eq. 2; (2025) Eq. 6",
    tags=("porosity", "density"),
))

_add(Equation(
    id="pore_diameter",
    name="Mean pore diameter (cylindrical pores)",
    category="Structure & porosity",
    latex=r"D_p = \frac{4V_p}{S}",
    inputs=(
        _V("V_p", "Pore volume", "cm^3/g", "specific_volume", 3.79, 0),
        _V("S", "Specific surface area", "m^2/g", "specific_surface", 350.15, 1e-9),
    ),
    output=_V("D_p", "Mean pore diameter", "nm", "length"),
    fn=lambda V_p, S: 4.0 * np.asarray(V_p, float) * 1e-6 / (np.asarray(S, float)) * 1e9,
    reference="Omranpour et al. (2024a) Eq. 3; (2025) Eq. 7",
    notes="Assumes cylindrical pores. Includes macropores, so it exceeds the DFT peak pore size.",
    tags=("porosity", "BET"),
))

_add(Equation(
    id="skeletal_density_mixture",
    name="Skeletal density by rule of mixtures",
    category="Structure & porosity",
    latex=r"\frac{1}{\rho_s}=\sum_i \frac{w_i}{\rho_i}",
    inputs=(
        _V("w", "Mass fractions (comma separated)", "-", "dimensionless", (0.93, 0.07),
           help="One per component; normalised automatically. Default is 7 wt% TEPI in TPU.",
           vector=True),
        _V("rho", "Component densities (comma separated)", "g/cm^3", "density", (1.11, 1.006),
           help="One per mass fraction, in the same order.", vector=True),
    ),
    output=_V("rho_s", "Skeletal density", "g/cm^3", "density"),
    fn=lambda w, rho: _rule_of_mixtures(w, rho),
    reference="Omranpour et al. (2024b) Eq. 2; (2025) Eq. 4",
    tags=("density", "composite"),
))

_add(Equation(
    id="relative_density",
    name="Relative density",
    category="Structure & porosity",
    latex=r"\rho_{rel} = \frac{\rho_b}{\rho_s}",
    inputs=(
        _V("rho_b", "Bulk density", "g/cm^3", "density", 0.15),
        _V("rho_s", "Skeletal density", "g/cm^3", "density", 1.116),
    ),
    output=_V("rho_rel", "Relative density", "-", "dimensionless"),
    fn=lambda rho_b, rho_s: np.asarray(rho_b, float) / np.asarray(rho_s, float),
    reference="Standard definition (Gibson & Ashby, 1997)",
    tags=("density", "scaling"),
))

_add(Equation(
    id="shrinkage",
    name="Drying shrinkage",
    category="Structure & porosity",
    latex=r"\text{Shrinkage}=\left(1-\frac{V_{final}}{V_{initial}}\right)\times100",
    inputs=(
        _V("V_final", "Final volume", "cm^3", "volume", 0.85, 0),
        _V("V_initial", "Initial volume", "cm^3", "volume", 1.0, 1e-12),
    ),
    output=_V("shrinkage", "Shrinkage", "%", "dimensionless"),
    fn=lambda V_final, V_initial: (1.0 - np.asarray(V_final, float) / np.asarray(V_initial, float)) * 100.0,
    reference="Omranpour et al. (2025) Eq. 3",
    tags=("drying", "aerogel"),
))

_add(Equation(
    id="volume_fraction",
    name="Volume fraction from mass fraction",
    category="Structure & porosity",
    latex=r"\varphi_i=\frac{w_i/\rho_i}{\sum_j w_j/\rho_j}",
    inputs=(
        _V("w_i", "Mass fraction of component i", "-", "dimensionless", 0.02, 0, 1),
        _V("rho_i", "Density of component i", "g/cm^3", "density", 1.5, 1e-9),
        _V("w_m", "Mass fraction of matrix", "-", "dimensionless", 0.98, 0, 1),
        _V("rho_m", "Density of matrix", "g/cm^3", "density", 1.11, 1e-9),
    ),
    output=_V("phi_i", "Volume fraction", "-", "dimensionless"),
    fn=lambda w_i, rho_i, w_m, rho_m: (np.asarray(w_i, float) / rho_i) / (np.asarray(w_i, float) / rho_i + np.asarray(w_m, float) / rho_m),
    reference="Standard composite relation",
    tags=("composite",),
))

_add(Equation(
    id="fibre_areal_density",
    name="Linear density (tex) of a fibre",
    category="Structure & porosity",
    latex=r"\text{tex}=\frac{\pi D^2}{4}\,\rho\times10^{3}",
    inputs=(
        _V("D", "Fibre diameter", "µm", "length", 90.0, 0),
        _V("rho", "Fibre density", "g/cm^3", "density", 0.151, 0),
    ),
    output=_V("tex", "Linear density", "-", "dimensionless", help="g per 1000 m"),
    fn=lambda D, rho: math.pi * (np.asarray(D, float) * 1e-6) ** 2 / 4.0 * (np.asarray(rho, float) * 1000.0) * 1e6,
    reference="Textile definition (g per 1000 m)",
    tags=("textile", "fibre"),
))

# =============================================================================
# 2. Thermal transport
# =============================================================================
_add(Equation(
    id="k_total",
    name="Total thermal conductivity (parallel contributions)",
    category="Thermal transport",
    latex=r"k_{tot}=k_{solid}+k_{gas}+k_{rad}+k_{conv}",
    inputs=(
        _V("k_solid", "Solid conduction", "mW/(m·K)", "thermal_conductivity", 5.3, 0),
        _V("k_gas", "Gas conduction", "mW/(m·K)", "thermal_conductivity", 18.7, 0),
        _V("k_rad", "Radiative conduction", "mW/(m·K)", "thermal_conductivity", 3.4, 0),
        _V("k_conv", "Convection", "mW/(m·K)", "thermal_conductivity", 0.0, 0),
    ),
    output=_V("k_tot", "Total conductivity", "mW/(m·K)", "thermal_conductivity"),
    fn=lambda k_solid, k_gas, k_rad, k_conv: np.asarray(k_solid, float) + np.asarray(k_gas, float) + np.asarray(k_rad, float) + np.asarray(k_conv, float),
    reference="Standard decomposition; Omranpour et al. (2025) Fig. 6d",
    tags=("thermal",),
))

_add(Equation(
    id="knudsen_number",
    name="Knudsen number",
    category="Thermal transport",
    latex=r"Kn=\frac{l_{mfp}}{D}",
    inputs=(
        _V("l_mfp", "Gas mean free path", "nm", "length", 70.0, 0),
        _V("D", "Pore diameter", "nm", "length", 30.0, 1e-9),
    ),
    output=_V("Kn", "Knudsen number", "-", "dimensionless"),
    fn=lambda l_mfp, D: np.asarray(l_mfp, float) / np.asarray(D, float),
    reference="Kaganer (1969)",
    notes="Kn ≫ 1 means molecules hit pore walls more often than each other, so gas conduction collapses.",
    tags=("thermal", "knudsen"),
))

_add(Equation(
    id="gas_conductivity_knudsen",
    name="Gas conduction with the Knudsen effect",
    category="Thermal transport",
    latex=r"k_{gas}=\frac{k_{gas,0}\,\Pi}{1+2\beta\,Kn},\qquad Kn=\frac{l_{mfp}}{D}",
    inputs=(
        _V("k_gas0", "Free-gas conductivity", "mW/(m·K)", "thermal_conductivity", K_AIR_STP, 0),
        _V("porosity", "Porosity", "%", "dimensionless", 86.5, 0, 100),
        _V("D", "Pore diameter", "nm", "length", 30.0, 1e-9),
        _V("beta", "Gas-wall coupling β", "-", "dimensionless", 1.6, 0),
        _V("l_mfp", "Mean free path", "nm", "length", MFP_AIR, 0),
    ),
    output=_V("k_gas", "Gas conduction", "mW/(m·K)", "thermal_conductivity"),
    fn=lambda k_gas0, porosity, D, beta, l_mfp: np.asarray(k_gas0, float) * (np.asarray(porosity, float) / 100.0)
    / (1.0 + 2.0 * np.asarray(beta, float) * np.asarray(l_mfp, float) / np.asarray(D, float)),
    reference="Kaganer (1969); Forest et al. (2015)",
    notes="β ≈ 1.5–2 for air. With 30 nm pores the gas term falls to roughly 3 mW/(m·K).",
    tags=("thermal", "knudsen", "aerogel"),
))

_add(Equation(
    id="mean_free_path",
    name="Mean free path of a gas",
    category="Thermal transport",
    latex=r"l_{mfp}=\frac{k_B T}{\sqrt{2}\,\pi d^2 p}",
    inputs=(
        _V("T", "Temperature", "°C", "temperature", 25.0, -273.0),
        _V("d", "Molecular (kinetic) diameter", "nm", "length", 0.364, 1e-6, help="N2 kinetic diameter 0.364 nm gives the canonical 70 nm for air"),
        _V("p", "Pressure", "Pa", "pressure", 101325.0, 1e-9),
    ),
    output=_V("l_mfp", "Mean free path", "nm", "length"),
    fn=lambda T, d, p: K_B * (np.asarray(T, float) + 273.15) / (math.sqrt(2.0) * math.pi * (np.asarray(d, float) * 1e-9) ** 2 * np.asarray(p, float)) * 1e9,
    reference="Kinetic theory of gases",
    notes="Air at 25 °C and 1 atm gives ≈70 nm, the value used throughout the papers.",
    tags=("thermal", "knudsen"),
))

_add(Equation(
    id="radiative_conductivity",
    name="Radiative conductivity (Rosseland)",
    category="Thermal transport",
    latex=r"k_{rad}=\frac{16\,n^{2}\sigma T^{3}}{3\,e^{*}\rho}",
    inputs=(
        _V("n", "Effective refractive index", "-", "dimensionless", 1.0, 0),
        _V("T", "Temperature", "°C", "temperature", 25.0, -273.0),
        _V("e_star", "Specific extinction coefficient", "m^2/g", "specific_surface", 0.05, 1e-12),
        _V("rho", "Density", "g/cm^3", "density", 0.151, 1e-12),
    ),
    output=_V("k_rad", "Radiative conductivity", "mW/(m·K)", "thermal_conductivity"),
    fn=lambda n, T, e_star, rho: 16.0 * np.asarray(n, float) ** 2 * SIGMA_SB * (np.asarray(T, float) + 273.15) ** 3
    / (3.0 * (np.asarray(e_star, float) * 1e3) * (np.asarray(rho, float) * 1e3)) * 1e3,
    reference="Rosseland diffusion approximation; Zhao et al. (2013)",
    notes="Scales with T³ — the reason opacifiers matter above ≈300 °C.",
    tags=("thermal", "radiation"),
))

_add(Equation(
    id="radiation_temperature_ratio",
    name="Radiative conductivity ratio between two temperatures",
    category="Thermal transport",
    latex=r"\frac{k_{rad}(T_2)}{k_{rad}(T_1)}=\left(\frac{T_2}{T_1}\right)^{3}",
    inputs=(
        _V("T1", "Reference temperature", "°C", "temperature", 25.0, -272.0),
        _V("T2", "Target temperature", "°C", "temperature", 300.0, -272.0),
    ),
    output=_V("ratio", "k_rad ratio", "-", "dimensionless"),
    fn=lambda T1, T2: ((np.asarray(T2, float) + 273.15) / (np.asarray(T1, float) + 273.15)) ** 3,
    reference="Consequence of the Rosseland approximation",
    notes="25 → 300 °C gives ≈7.1× more radiative transport at constant extinction.",
    tags=("thermal", "radiation"),
))

_add(Equation(
    id="thermal_diffusivity",
    name="Thermal diffusivity",
    category="Thermal transport",
    latex=r"\alpha=\frac{k}{\rho c_p}",
    inputs=(
        _V("k", "Thermal conductivity", "mW/(m·K)", "thermal_conductivity", 27.7, 0),
        _V("rho", "Density", "g/cm^3", "density", 0.1508, 1e-12),
        _V("c_p", "Specific heat", "J/(kg·K)", "specific_heat", 1000.0, 1e-12),
    ),
    output=_V("alpha", "Thermal diffusivity", "mm^2/s", "thermal_diffusivity"),
    fn=lambda k, rho, c_p: (np.asarray(k, float) * 1e-3) / ((np.asarray(rho, float) * 1000.0) * np.asarray(c_p, float)) * 1e6,
    reference="Omranpour et al. (2025) Eq. 8",
    tags=("thermal",),
))

_add(Equation(
    id="thermal_effusivity",
    name="Thermal effusivity",
    category="Thermal transport",
    latex=r"e=\sqrt{k\,\rho\,c_p}",
    inputs=(
        _V("k", "Thermal conductivity", "mW/(m·K)", "thermal_conductivity", 27.7, 0),
        _V("rho", "Density", "g/cm^3", "density", 0.1508, 0),
        _V("c_p", "Specific heat", "J/(kg·K)", "specific_heat", 1000.0, 0),
    ),
    output=_V("e", "Thermal effusivity", "W·s^0.5/(m^2·K)", "effusivity"),
    fn=lambda k, rho, c_p: np.sqrt((np.asarray(k, float) * 1e-3) * (np.asarray(rho, float) * 1000.0) * np.asarray(c_p, float)),
    reference="Omranpour et al. (2025) Eq. 9",
    notes="How quickly a fabric draws heat from skin — the 'warm touch' metric.",
    tags=("thermal", "textile"),
))

_add(Equation(
    id="effusivity_from_k_alpha",
    name="Effusivity from conductivity and diffusivity",
    category="Thermal transport",
    latex=r"e=\frac{k}{\sqrt{\alpha}}",
    inputs=(
        _V("k", "Thermal conductivity", "mW/(m·K)", "thermal_conductivity", 27.7, 0),
        _V("alpha", "Thermal diffusivity", "mm^2/s", "thermal_diffusivity", 0.196, 1e-12),
    ),
    output=_V("e", "Thermal effusivity", "W·s^0.5/(m^2·K)", "effusivity"),
    fn=lambda k, alpha: (np.asarray(k, float) * 1e-3) / np.sqrt(np.asarray(alpha, float) * 1e-6),
    reference="Omranpour et al. (2025) Eq. 10",
    notes="Useful consistency check on Hot Disk output: k, α and e are not independent.",
    tags=("thermal", "qa"),
))

_add(Equation(
    id="r_value",
    name="Thermal resistance (R-value) of a layer",
    category="Thermal transport",
    latex=r"R=\frac{t}{k}",
    inputs=(
        _V("t", "Thickness", "mm", "length", 5.0, 0),
        _V("k", "Thermal conductivity", "mW/(m·K)", "thermal_conductivity", 29.0, 1e-9),
    ),
    output=_V("R", "Thermal resistance", "m^2·K/W", "thermal_resistance"),
    fn=lambda t, k: (np.asarray(t, float) * 1e-3) / (np.asarray(k, float) * 1e-3),
    reference="Omranpour et al. (2024b) Eq. 5; Hoseini et al. (2016)",
    tags=("thermal", "textile"),
))

_add(Equation(
    id="clo_value",
    name="Clo value of an insulating layer",
    category="Thermal transport",
    latex=r"\text{clo}=\frac{R}{0.155}",
    inputs=(_V("R", "Thermal resistance", "m^2·K/W", "thermal_resistance", 0.172, 0),),
    # clo is a thermal resistance, not a bare number: 1 clo = 0.155 m²·K/W. Declaring it
    # that way lets the Calculator offer m²·K/W and clo as interchangeable output units.
    output=_V("clo", "Clo value", "clo", "thermal_resistance"),
    fn=lambda R: np.asarray(R, float) / 0.155,
    reference="Textile comfort definition (1 clo = 0.155 m²·K/W)",
    tags=("textile", "comfort"),
))

_add(Equation(
    id="k_model_aerogel_fibre",
    name="Predicted conductivity of a porous fibre (three mechanisms)",
    category="Thermal transport",
    latex=r"k=k_{s0}\left(\frac{\rho}{\rho_s}\right)^{\tau}+\frac{k_{gas,0}\Pi}{1+2\beta Kn}+\frac{16n^{2}\sigma T^{3}}{3e^{*}\rho}",
    inputs=(
        _V("k_s0", "Solid-phase conductivity", "mW/(m·K)", "thermal_conductivity", 1000.0, 0, help="Bulk conductivity of the skeleton material"),
        _V("rho_b", "Bulk density", "g/cm^3", "density", 0.1508, 0),
        _V("rho_s", "Skeletal density", "g/cm^3", "density", 1.116, 1e-9),
        _V("tau", "Solid-network exponent", "-", "dimensionless", 1.5, 0, help="1.5–2 for tortuous aerogel networks"),
        _V("D", "Pore diameter", "nm", "length", 30.0, 1e-9),
        _V("beta", "Gas-wall coupling β", "-", "dimensionless", 1.6, 0),
        _V("T", "Temperature", "°C", "temperature", 25.0, -273.0),
        _V("e_star", "Specific extinction", "m^2/g", "specific_surface", 0.05, 1e-12),
    ),
    output=_V("k", "Predicted conductivity", "mW/(m·K)", "thermal_conductivity"),
    fn=lambda k_s0, rho_b, rho_s, tau, D, beta, T, e_star: _k_model(k_s0, rho_b, rho_s, tau, D, beta, T, e_star),
    reference="Combined model after Lu et al. (1992), Forest et al. (2015), Wang et al. (2017)",
    notes="Use to ask 'which mechanism dominates?' — the app plots the three contributions separately.",
    tags=("thermal", "model"),
))

# =============================================================================
# 3. Mechanical
# =============================================================================
_add(Equation(
    id="tensile_stress",
    name="Engineering stress",
    category="Mechanical",
    latex=r"\sigma=\frac{F}{A_0},\qquad A_0=\frac{\pi D^2}{4}",
    inputs=(
        _V("F", "Force", "N", "force", 0.074, 0),
        _V("D", "Fibre diameter", "µm", "length", 90.0, 1e-9),
    ),
    output=_V("sigma", "Engineering stress", "MPa", "stress"),
    fn=lambda F, D: np.asarray(F, float) / (math.pi * (np.asarray(D, float) * 1e-6) ** 2 / 4.0) * 1e-6,
    reference="Standard single-fibre tensile definition (ASTM D3822)",
    tags=("mechanical", "tensile"),
))

_add(Equation(
    id="engineering_strain",
    name="Engineering strain",
    category="Mechanical",
    latex=r"\varepsilon=\frac{\Delta L}{L_0}\times100",
    inputs=(
        _V("dL", "Extension", "mm", "length", 80.0, 0),
        _V("L0", "Gauge length", "mm", "length", 80.0, 1e-9),
    ),
    output=_V("strain", "Strain", "%", "dimensionless"),
    fn=lambda dL, L0: np.asarray(dL, float) / np.asarray(L0, float) * 100.0,
    reference="Standard definition",
    tags=("mechanical", "tensile"),
))

_add(Equation(
    id="youngs_modulus",
    name="Young's modulus (secant)",
    category="Mechanical",
    latex=r"E=\frac{\sigma_2-\sigma_1}{\varepsilon_2-\varepsilon_1}",
    inputs=(
        _V("sigma1", "Stress 1", "MPa", "stress", 0.0),
        _V("eps1", "Strain 1", "%", "dimensionless", 0.0),
        _V("sigma2", "Stress 2", "MPa", "stress", 1.2),
        _V("eps2", "Strain 2", "%", "dimensionless", 5.0),
    ),
    output=_V("E", "Young's modulus", "MPa", "stress"),
    fn=lambda sigma1, eps1, sigma2, eps2: (np.asarray(sigma2, float) - np.asarray(sigma1, float)) / ((np.asarray(eps2, float) - np.asarray(eps1, float)) / 100.0),
    reference="Standard definition",
    tags=("mechanical",),
))

_add(Equation(
    id="specific_strength",
    name="Specific strength",
    category="Mechanical",
    latex=r"\sigma_{spec}=\frac{\sigma}{\rho}",
    inputs=(
        _V("sigma", "Tensile strength", "MPa", "stress", 11.6, 0),
        _V("rho", "Density", "g/cm^3", "density", 0.1508, 1e-9),
    ),
    output=_V("sigma_spec", "Specific strength", "-", "dimensionless", help="MPa·cm³/g"),
    fn=lambda sigma, rho: np.asarray(sigma, float) / np.asarray(rho, float),
    reference="Standard definition",
    tags=("mechanical",),
))

_add(Equation(
    id="second_moment_circle",
    name="Second moment of area (circular fibre)",
    category="Mechanical",
    latex=r"I=\frac{\pi D^{4}}{64}",
    inputs=(_V("D", "Fibre diameter", "µm", "length", 90.0, 0),),
    output=_V("I", "Second moment of area", "m^4", "second_moment"),
    fn=lambda D: math.pi * (np.asarray(D, float) * 1e-6) ** 4 / 64.0,
    reference="Omranpour et al. (2024a) Eq. 5",
    tags=("mechanical", "textile"),
))

_add(Equation(
    id="bending_rigidity",
    name="Bending rigidity of a fibre",
    category="Mechanical",
    latex=r"EI = E\,\frac{\pi D^{4}}{64}",
    inputs=(
        _V("E", "Young's modulus", "MPa", "stress", 3.51, 0),
        _V("D", "Fibre diameter", "µm", "length", 90.0, 0),
    ),
    output=_V("EI", "Bending rigidity", "-", "dimensionless", help="N·m²"),
    fn=lambda E, D: (np.asarray(E, float) * 1e6) * math.pi * (np.asarray(D, float) * 1e-6) ** 4 / 64.0,
    reference="Omranpour et al. (2024a) Eq. 4–5; Bao et al. (2021)",
    notes="Flexible phase-change fibres stay wearable below ≈1.22×10⁻⁹ N·m².",
    tags=("mechanical", "textile", "comfort"),
))

_add(Equation(
    id="euler_buckling",
    name="Euler critical buckling load",
    category="Mechanical",
    latex=r"P_{cr}=\frac{\pi^{2}EI}{(KL)^{2}}",
    inputs=(
        _V("E", "Young's modulus", "MPa", "stress", 3.51, 0),
        _V("D", "Fibre diameter", "µm", "length", 90.0, 0),
        _V("L", "Free length", "mm", "length", 10.0, 1e-9),
        _V("K", "End-condition factor", "-", "dimensionless", 1.0, 0.1),
    ),
    output=_V("P_cr", "Critical load", "mN", "force"),
    fn=lambda E, D, L, K: (math.pi ** 2 * (np.asarray(E, float) * 1e6) * math.pi * (np.asarray(D, float) * 1e-6) ** 4 / 64.0)
    / (np.asarray(K, float) * np.asarray(L, float) * 1e-3) ** 2 * 1e3,
    reference="Euler buckling; Omranpour et al. (2025) §3.6",
    notes="P_cr ∝ D⁴ — halving fibre diameter makes it 16× easier to bend.",
    tags=("mechanical", "textile"),
))

_add(Equation(
    id="halpin_tsai",
    name="Halpin–Tsai / Halpin–Kardos longitudinal modulus",
    category="Mechanical",
    latex=r"E_{\parallel}=E_m\frac{1+\xi\eta\varphi_f}{1-\eta\varphi_f},\quad \eta=\frac{E_f/E_m-1}{E_f/E_m+\xi},\quad \xi=2\frac{l}{d}",
    inputs=(
        _V("E_m", "Matrix modulus", "MPa", "stress", 12.0, 1e-9),
        _V("E_f", "Fibre modulus", "MPa", "stress", 100000.0, 1e-9),
        _V("phi_f", "Fibre volume fraction", "-", "dimensionless", 0.0148, 0, 1),
        _V("l_over_d", "Fibre aspect ratio l/d", "-", "dimensionless", 50.0, 0),
    ),
    output=_V("E_par", "Longitudinal modulus", "MPa", "stress"),
    fn=lambda E_m, E_f, phi_f, l_over_d: _halpin_tsai(E_m, E_f, phi_f, l_over_d),
    reference="Halpin & Kardos (1976); Omranpour et al. (2025) Eqs. 11–13",
    tags=("mechanical", "composite", "model"),
))

_add(Equation(
    id="density_scaling_modulus",
    name="Stiffness–density power law",
    category="Mechanical",
    latex=r"E=E_m\left(\frac{\rho}{\rho_s}\right)^{n}",
    inputs=(
        _V("E_m", "Solid-phase modulus", "MPa", "stress", 14.12, 0),
        _V("rho", "Aerogel density", "g/cm^3", "density", 0.1508, 0),
        _V("rho_s", "Solid density", "g/cm^3", "density", 1.116, 1e-9),
        _V("n", "Scaling exponent n", "-", "dimensionless", 0.78, 0),
    ),
    output=_V("E", "Modulus", "MPa", "stress"),
    fn=lambda E_m, rho, rho_s, n: np.asarray(E_m, float) * (np.asarray(rho, float) / np.asarray(rho_s, float)) ** np.asarray(n, float),
    reference="Gibson & Ashby (1997); Omranpour et al. (2025) Eq. 14",
    notes="n ≈ 2 for open-cell foams, 3–4 for silica aerogels, 0.78 fitted for the nanofibril fibres.",
    tags=("mechanical", "scaling"),
))

_add(Equation(
    id="density_scaling_crosslinked",
    name="Stiffness–density law with a crosslinking term",
    category="Mechanical",
    latex=r"E=E_m\left(\frac{\rho}{\rho_s}\right)^{n}+K\,C_{TPU}^{\,m}",
    inputs=(
        _V("E_m", "Solid-phase modulus", "MPa", "stress", 14.12, 0),
        _V("rho", "Aerogel density", "g/cm^3", "density", 0.1508, 0),
        _V("rho_s", "Solid density", "g/cm^3", "density", 1.116, 1e-9),
        _V("n", "Scaling exponent n", "-", "dimensionless", 0.78, 0),
        _V("K", "Crosslink constant K", "-", "dimensionless", 33.65),
        _V("C", "Polymer concentration C", "-", "dimensionless", 0.04, 0),
        _V("m", "Concentration exponent m", "-", "dimensionless", 1.39),
    ),
    output=_V("E", "Modulus", "MPa", "stress"),
    fn=lambda E_m, rho, rho_s, n, K, C, m: np.asarray(E_m, float) * (np.asarray(rho, float) / np.asarray(rho_s, float)) ** np.asarray(n, float)
    + np.asarray(K, float) * np.asarray(C, float) ** np.asarray(m, float),
    reference="Omranpour et al. (2025) Eq. 16",
    tags=("mechanical", "scaling", "model"),
))

_add(Equation(
    id="scaling_exponent_two_points",
    name="Scaling exponent from two (ρ, E) points",
    category="Mechanical",
    latex=r"n=\frac{\ln(E_2/E_1)}{\ln(\rho_2/\rho_1)}",
    inputs=(
        _V("rho1", "Density 1", "g/cm^3", "density", 0.132, 1e-12),
        _V("E1", "Modulus 1", "MPa", "stress", 9.15, 1e-12),
        _V("rho2", "Density 2", "g/cm^3", "density", 0.157, 1e-12),
        _V("E2", "Modulus 2", "MPa", "stress", 2.87, 1e-12),
    ),
    output=_V("n", "Scaling exponent", "-", "dimensionless"),
    fn=lambda rho1, E1, rho2, E2: np.log(np.asarray(E2, float) / np.asarray(E1, float)) / np.log(np.asarray(rho2, float) / np.asarray(rho1, float)),
    reference="Definition; see Ma et al. (2000)",
    notes="A negative value means stiffness fell while density rose — a sign the exponent is not identifiable from those points alone.",
    tags=("mechanical", "scaling", "qa"),
))

_add(Equation(
    id="elastic_recovery",
    name="Elastic recovery and permanent set",
    category="Mechanical",
    latex=r"ER=\varepsilon_{max}-PS,\qquad \frac{ER}{\varepsilon_{max}}\times100",
    inputs=(
        _V("eps_max", "Maximum strain", "%", "dimensionless", 100.0, 0),
        _V("PS", "Permanent set", "%", "dimensionless", 5.3, 0),
    ),
    output=_V("ER_ratio", "Elastic recovery ratio", "%", "dimensionless"),
    fn=lambda eps_max, PS: (np.asarray(eps_max, float) - np.asarray(PS, float)) / np.asarray(eps_max, float) * 100.0,
    reference="Omranpour et al. (2024b) Eq. 4",
    tags=("mechanical", "cyclic"),
))

_add(Equation(
    id="shape_recovery",
    name="Shape recovery after compression",
    category="Mechanical",
    latex=r"S=\frac{d_2}{d_1}\times100",
    inputs=(
        _V("d2", "Diameter after compression", "mm", "length", 4.9, 0),
        _V("d1", "Original diameter", "mm", "length", 5.0, 1e-9),
    ),
    output=_V("S", "Shape recovery", "%", "dimensionless"),
    fn=lambda d2, d1: np.asarray(d2, float) / np.asarray(d1, float) * 100.0,
    reference="Omranpour et al. (2024b) Eq. 6",
    tags=("mechanical", "cyclic"),
))

# =============================================================================
# 4. Fatigue & durability
# =============================================================================
_add(Equation(
    id="swt_amplitude",
    name="Smith–Watson–Topper equivalent amplitude",
    category="Fatigue & durability",
    latex=r"\sigma_{ar}=\sqrt{\sigma_a\,\sigma_{max}}",
    inputs=(
        _V("sigma_a", "Stress amplitude", "MPa", "stress", 3.6, 0),
        _V("sigma_max", "Maximum stress", "MPa", "stress", 7.2, 0),
    ),
    output=_V("sigma_ar", "Equivalent amplitude (R = −1)", "MPa", "stress"),
    fn=lambda sigma_a, sigma_max: np.sqrt(np.asarray(sigma_a, float) * np.asarray(sigma_max, float)),
    reference="Omranpour et al. (2024a) Eq. 6; Łagoda et al. (2022)",
    notes="For zero-to-tension loading (R = 0), σa = σmax/2 so σar = σmax/√2.",
    tags=("fatigue",),
))

_add(Equation(
    id="strain_life",
    name="Strain-life (Basquin–Manson–Coffin)",
    category="Fatigue & durability",
    latex=r"\varepsilon_a=\frac{\sigma_f'}{E}(2N_f)^{b}+\varepsilon_f'(2N_f)^{c}",
    inputs=(
        _V("sigma_f", "Fatigue strength coefficient σ'f", "MPa", "stress", 7.21, 0),
        _V("E", "Young's modulus", "MPa", "stress", 18.0, 1e-9),
        _V("b", "Fatigue strength exponent b", "-", "dimensionless", -0.063),
        _V("eps_f", "Fatigue ductility coefficient ε'f", "-", "dimensionless", 0.34, 0),
        _V("c", "Fatigue ductility exponent c", "-", "dimensionless", -0.14),
        _V("Nf", "Cycles to failure", "cycles", "cycles", 1000.0, 0.5),
    ),
    output=_V("eps_a", "Strain amplitude", "-", "dimensionless"),
    fn=lambda sigma_f, E, b, eps_f, c, Nf: (np.asarray(sigma_f, float) / np.asarray(E, float)) * (2.0 * np.asarray(Nf, float)) ** np.asarray(b, float)
    + np.asarray(eps_f, float) * (2.0 * np.asarray(Nf, float)) ** np.asarray(c, float),
    reference="Omranpour et al. (2024a) Eq. 7; Dowling (2013)",
    tags=("fatigue", "model"),
))

_add(Equation(
    id="strain_life_morrow",
    name="Strain-life with Morrow mean-stress correction",
    category="Fatigue & durability",
    latex=r"\varepsilon_a=\frac{\sigma_f'-\sigma_m}{E}(2N_f)^{b}+\varepsilon_f'(2N_f)^{c}",
    inputs=(
        _V("sigma_f", "σ'f", "MPa", "stress", 7.21, 0),
        _V("sigma_m", "Mean stress σm", "MPa", "stress", 0.0),
        _V("E", "Young's modulus", "MPa", "stress", 18.0, 1e-9),
        _V("b", "b", "-", "dimensionless", -0.063),
        _V("eps_f", "ε'f", "-", "dimensionless", 0.34, 0),
        _V("c", "c", "-", "dimensionless", -0.14),
        _V("Nf", "Cycles to failure", "cycles", "cycles", 1000.0, 0.5),
    ),
    output=_V("eps_a", "Strain amplitude", "-", "dimensionless"),
    fn=lambda sigma_f, sigma_m, E, b, eps_f, c, Nf: ((np.asarray(sigma_f, float) - np.asarray(sigma_m, float)) / np.asarray(E, float))
    * (2.0 * np.asarray(Nf, float)) ** np.asarray(b, float) + np.asarray(eps_f, float) * (2.0 * np.asarray(Nf, float)) ** np.asarray(c, float),
    reference="Omranpour et al. (2024a) Table 3 form; Dowling (2013)",
    tags=("fatigue", "model"),
))

_add(Equation(
    id="transition_life",
    name="Transition fatigue life",
    category="Fatigue & durability",
    latex=r"2N_t=\left(\frac{\varepsilon_f' E}{\sigma_f'}\right)^{\frac{1}{b-c}}",
    inputs=(
        _V("eps_f", "ε'f", "-", "dimensionless", 0.34, 1e-12),
        _V("E", "Young's modulus", "MPa", "stress", 18.0, 0),
        _V("sigma_f", "σ'f", "MPa", "stress", 7.21, 1e-12),
        _V("b", "b", "-", "dimensionless", -0.063),
        _V("c", "c", "-", "dimensionless", -0.14),
    ),
    output=_V("two_Nt", "Transition life", "reversals", "cycles"),
    fn=lambda eps_f, E, sigma_f, b, c: (np.asarray(eps_f, float) * np.asarray(E, float) / np.asarray(sigma_f, float)) ** (1.0 / (np.asarray(b, float) - np.asarray(c, float))),
    reference="Dowling (2013); used in Omranpour et al. (2024a)",
    notes="Below one reversal means elastic strain dominates at every practical life.",
    tags=("fatigue",),
))

_add(Equation(
    id="ratcheting_strain",
    name="Ratcheting strain",
    category="Fatigue & durability",
    latex=r"\varepsilon_r=\frac{\varepsilon_{max}+\varepsilon_{min}}{2}",
    inputs=(
        _V("eps_max", "Maximum strain in cycle", "%", "dimensionless", 64.0),
        _V("eps_min", "Minimum strain in cycle", "%", "dimensionless", 0.0),
    ),
    output=_V("eps_r", "Ratcheting strain", "%", "dimensionless"),
    fn=lambda eps_max, eps_min: (np.asarray(eps_max, float) + np.asarray(eps_min, float)) / 2.0,
    reference="Omranpour et al. (2024a) Eq. 8",
    tags=("fatigue", "cyclic"),
))

_add(Equation(
    id="basquin_life",
    name="Cycles to failure from Basquin's law",
    category="Fatigue & durability",
    latex=r"N_f=\frac{1}{2}\left(\frac{\sigma_a}{\sigma_f'}\right)^{1/b}",
    inputs=(
        _V("sigma_a", "Stress amplitude", "MPa", "stress", 4.0, 1e-12),
        _V("sigma_f", "σ'f", "MPa", "stress", 7.21, 1e-12),
        _V("b", "b", "-", "dimensionless", -0.063),
    ),
    output=_V("Nf", "Cycles to failure", "cycles", "cycles"),
    fn=lambda sigma_a, sigma_f, b: 0.5 * (np.asarray(sigma_a, float) / np.asarray(sigma_f, float)) ** (1.0 / np.asarray(b, float)),
    reference="Basquin's relation; Dowling (2013)",
    tags=("fatigue",),
))

# =============================================================================
# 5. Rheology & processing
# =============================================================================
_add(Equation(
    id="herschel_bulkley",
    name="Herschel–Bulkley shear stress",
    category="Rheology & processing",
    latex=r"\tau=\tau_y+K\dot{\gamma}^{\,n}",
    inputs=(
        _V("tau_y", "Yield stress τy", "Pa", "pressure", 6000.0, 0),
        _V("K", "Consistency index K", "-", "dimensionless", 50.0, 0),
        _V("gamma_dot", "Shear rate", "1/s", "shear_rate", 1.0, 0),
        _V("n", "Flow index n", "-", "dimensionless", 0.5, 0),
    ),
    output=_V("tau", "Shear stress", "Pa", "pressure"),
    fn=lambda tau_y, K, gamma_dot, n: np.asarray(tau_y, float) + np.asarray(K, float) * np.asarray(gamma_dot, float) ** np.asarray(n, float),
    reference="Herschel–Bulkley model; Omranpour et al. (2024a) §3.1",
    tags=("rheology", "spinning"),
))

_add(Equation(
    id="viscosity_ratio",
    name="Viscosity ratio of a blend",
    category="Rheology & processing",
    latex=r"p=\frac{\eta_d}{\eta_m}",
    inputs=(
        _V("eta_d", "Dispersed-phase viscosity", "Pa·s", "viscosity", 300.0, 0),
        _V("eta_m", "Matrix viscosity", "Pa·s", "viscosity", 600.0, 1e-12),
    ),
    output=_V("p", "Viscosity ratio", "-", "dimensionless"),
    fn=lambda eta_d, eta_m: np.asarray(eta_d, float) / np.asarray(eta_m, float),
    reference="Favis & Chalifoux (1987); Omranpour et al. (2025) §3.3",
    notes="Fibrillation works best for 0.3 ≤ p ≤ 1.5.",
    tags=("rheology", "fibrillation"),
))

_add(Equation(
    id="capillary_number",
    name="Capillary number (droplet deformation)",
    category="Rheology & processing",
    latex=r"Ca=\frac{\eta_m\dot{\gamma}R}{\Gamma}",
    inputs=(
        _V("eta_m", "Matrix viscosity", "Pa·s", "viscosity", 600.0, 0),
        _V("gamma_dot", "Deformation rate", "1/s", "shear_rate", 100.0, 0),
        _V("R", "Droplet radius", "µm", "length", 1.0, 0),
        _V("Gamma", "Interfacial tension", "mN/m", "surface_tension", 5.0, 1e-12),
    ),
    output=_V("Ca", "Capillary number", "-", "dimensionless"),
    fn=lambda eta_m, gamma_dot, R, Gamma: np.asarray(eta_m, float) * np.asarray(gamma_dot, float) * (np.asarray(R, float) * 1e-6) / (np.asarray(Gamma, float) * 1e-3),
    reference="Grace (1982); Omranpour et al. (2025)",
    tags=("rheology", "fibrillation"),
))

_add(Equation(
    id="draw_ratio",
    name="Draw ratio of a spinline",
    category="Rheology & processing",
    latex=r"DR=\frac{V_{take-up}}{V_{exit}},\qquad V_{exit}=\frac{Q}{A}",
    inputs=(
        _V("V_takeup", "Take-up speed", "m/min", "velocity", 1.0, 0),
        _V("Q", "Volumetric flow rate", "mL/h", "flow_rate", 2.0, 0),
        _V("d_nozzle", "Nozzle inner diameter", "µm", "length", 159.0, 1e-9),
    ),
    output=_V("DR", "Draw ratio", "-", "dimensionless"),
    fn=lambda V_takeup, Q, d_nozzle: _draw_ratio(V_takeup, Q, d_nozzle),
    reference="Standard spinning relation; applied to Omranpour et al. (2025)",
    notes="DR < 1 means the filament is not drawn down at the nozzle.",
    tags=("spinning", "process"),
))

_add(Equation(
    id="nozzle_exit_velocity",
    name="Mean nozzle exit velocity",
    category="Rheology & processing",
    latex=r"V_{exit}=\frac{Q}{\pi d^{2}/4}",
    inputs=(
        _V("Q", "Volumetric flow rate", "mL/h", "flow_rate", 2.0, 0),
        _V("d_nozzle", "Nozzle inner diameter", "µm", "length", 159.0, 1e-9),
    ),
    output=_V("V_exit", "Exit velocity", "m/min", "velocity"),
    fn=lambda Q, d_nozzle: (np.asarray(Q, float) * 1e-6 / 3600.0) / (math.pi * (np.asarray(d_nozzle, float) * 1e-6) ** 2 / 4.0) * 60.0,
    reference="Continuity",
    tags=("spinning", "process"),
))

_add(Equation(
    id="tan_delta",
    name="Loss tangent and phase angle",
    category="Rheology & processing",
    latex=r"\tan\delta=\frac{G''}{G'},\qquad \delta=\arctan\left(\frac{G''}{G'}\right)",
    inputs=(
        _V("G_storage", "Storage modulus G′", "Pa", "pressure", 30000.0, 1e-12),
        _V("G_loss", "Loss modulus G″", "Pa", "pressure", 5000.0, 0),
    ),
    output=_V("delta", "Phase angle δ", "deg", "angle"),
    fn=lambda G_storage, G_loss: np.degrees(np.arctan(np.asarray(G_loss, float) / np.asarray(G_storage, float))),
    reference="Standard viscoelastic definition; Omranpour et al. (2024a) Fig. 2f",
    notes="δ < 45° means solid-like; the pastes in Paper 1 sit near 10° before yielding.",
    tags=("rheology",),
))

_add(Equation(
    id="complex_modulus",
    name="Complex modulus",
    category="Rheology & processing",
    latex=r"|G^*|=\sqrt{G'^2+G''^2}",
    inputs=(
        _V("G_storage", "G′", "Pa", "pressure", 30000.0, 0),
        _V("G_loss", "G″", "Pa", "pressure", 5000.0, 0),
    ),
    output=_V("G_star", "Complex modulus", "Pa", "pressure"),
    fn=lambda G_storage, G_loss: np.hypot(np.asarray(G_storage, float), np.asarray(G_loss, float)),
    reference="Standard definition",
    tags=("rheology",),
))

_add(Equation(
    id="diffusion_time",
    name="Characteristic diffusion time",
    category="Rheology & processing",
    latex=r"t\approx\frac{R^{2}}{D}",
    inputs=(
        _V("R", "Radius", "µm", "length", 50.0, 0),
        _V("D_diff", "Diffusion coefficient", "-", "dimensionless", 1e-9, 1e-30, help="m²/s"),
    ),
    output=_V("t", "Diffusion time", "s", "time"),
    fn=lambda R, D_diff: (np.asarray(R, float) * 1e-6) ** 2 / np.asarray(D_diff, float),
    reference="Scaling estimate for solvent exchange / gas saturation",
    notes="A 50 µm fibre exchanges solvent in seconds — the 72 h in the papers is batch handling, not diffusion.",
    tags=("process", "scaling"),
))

_add(Equation(
    id="deborah_recovery",
    name="Recovery Deborah number",
    category="Rheology & processing",
    latex=r"De_r=\frac{t_{rec}}{t_{tr}}",
    inputs=(
        _V("t_rec", "Structural recovery time", "s", "time", 1.0, 0),
        _V("t_tr", "Transit time nozzle → bath", "s", "time", 2.0, 1e-9),
    ),
    output=_V("De_r", "Recovery Deborah number", "-", "dimensionless"),
    fn=lambda t_rec, t_tr: np.asarray(t_rec, float) / np.asarray(t_tr, float),
    reference="Defined for thixotropic spinning dopes (see study pack, Proposal A)",
    notes="De_r < 1 means the paste rebuilds its structure before it reaches the bath.",
    tags=("rheology", "spinning"),
))

_add(Equation(
    id="yield_number",
    name="Yield number (filament shape retention)",
    category="Rheology & processing",
    latex=r"Y=\frac{\tau_y R}{\Gamma}",
    inputs=(
        _V("tau_y", "Yield stress", "Pa", "pressure", 6000.0, 0),
        _V("R", "Filament radius", "µm", "length", 250.0, 0),
        _V("Gamma", "Interfacial tension", "mN/m", "surface_tension", 5.0, 1e-12),
    ),
    output=_V("Y", "Yield number", "-", "dimensionless"),
    fn=lambda tau_y, R, Gamma: np.asarray(tau_y, float) * (np.asarray(R, float) * 1e-6) / (np.asarray(Gamma, float) * 1e-3),
    reference="Defined for yield-stress dopes (see study pack, Proposal A)",
    notes="Y ≫ 1 means yield stress beats capillary break-up, so the filament keeps its shape.",
    tags=("rheology", "spinning"),
))

# =============================================================================
# 6. Chemistry & thermal analysis
# =============================================================================
_add(Equation(
    id="gel_content",
    name="Gel content (crosslink fraction)",
    category="Chemistry & thermal analysis",
    latex=r"\text{Gel}=\frac{W_{gel}}{W_0}\times100",
    inputs=(
        _V("W_gel", "Insoluble mass after extraction", "mg", "mass", 82.0, 0),
        _V("W_0", "Initial mass", "mg", "mass", 100.0, 1e-9),
    ),
    output=_V("gel", "Gel content", "%", "dimensionless"),
    fn=lambda W_gel, W_0: np.asarray(W_gel, float) / np.asarray(W_0, float) * 100.0,
    reference="ASTM D2765; Omranpour et al. (2025) Eq. 1",
    notes="Above 80 % confirms a crosslinked network in the nanofibrils.",
    tags=("chemistry", "crosslinking"),
))

_add(Equation(
    id="crystallinity_xrd",
    name="Crystallinity from XRD peak areas",
    category="Chemistry & thermal analysis",
    latex=r"X_c=\frac{A_{cryst}}{A_{total}}\times100",
    inputs=(
        _V("A_cryst", "Area under crystalline peaks", "-", "dimensionless", 78.0, 0),
        _V("A_total", "Total area under the pattern", "-", "dimensionless", 100.0, 1e-12),
    ),
    output=_V("X_c", "Crystallinity", "%", "dimensionless"),
    fn=lambda A_cryst, A_total: np.asarray(A_cryst, float) / np.asarray(A_total, float) * 100.0,
    reference="Omranpour et al. (2024b) Eq. 3",
    tags=("chemistry", "xrd"),
))

_add(Equation(
    id="crystallinity_dsc",
    name="Crystallinity from DSC enthalpies",
    category="Chemistry & thermal analysis",
    latex=r"X_c=\frac{\Delta H_m-\Delta H_{cc}}{w\,\Delta H_{100}}\times100",
    inputs=(
        _V("dH_m", "Melting enthalpy", "J/g", "enthalpy", 7.49, 0),
        _V("dH_cc", "Cold-crystallisation enthalpy", "J/g", "enthalpy", 0.0, 0),
        _V("w", "Mass fraction of the polymer", "-", "dimensionless", 0.67, 1e-9, 1),
        _V("dH_100", "Enthalpy of the 100 % crystal", "J/g", "enthalpy", 196.8, 1e-9),
    ),
    output=_V("X_c", "Crystallinity", "%", "dimensionless"),
    fn=lambda dH_m, dH_cc, w, dH_100: (np.asarray(dH_m, float) - np.asarray(dH_cc, float)) / (np.asarray(w, float) * np.asarray(dH_100, float)) * 100.0,
    reference="Standard DSC relation",
    tags=("chemistry", "dsc"),
))

_add(Equation(
    id="normalised_enthalpy",
    name="Enthalpy normalised to polymer content",
    category="Chemistry & thermal analysis",
    latex=r"\Delta H_{norm}=\frac{\Delta H}{w_{polymer}}",
    inputs=(
        _V("dH", "Measured enthalpy", "J/g", "enthalpy", 7.49, 0),
        _V("w_polymer", "Polymer mass fraction", "-", "dimensionless", 0.67, 1e-9, 1),
    ),
    output=_V("dH_norm", "Normalised enthalpy", "J/g", "enthalpy"),
    fn=lambda dH, w_polymer: np.asarray(dH, float) / np.asarray(w_polymer, float),
    reference="Omranpour et al. (2024a) Table 2",
    tags=("chemistry", "dsc"),
))

_add(Equation(
    id="wetting_coefficient",
    name="Wetting coefficient (phase localisation)",
    category="Chemistry & thermal analysis",
    latex=r"\omega_a=\frac{\gamma_{13}-\gamma_{23}}{\gamma_{12}}",
    inputs=(
        _V("g13", "Interfacial tension filler–polymer 1", "mN/m", "surface_tension", 5.0),
        _V("g23", "Interfacial tension filler–polymer 2", "mN/m", "surface_tension", 12.0),
        _V("g12", "Interfacial tension polymer 1–2", "mN/m", "surface_tension", 4.0, 1e-12),
    ),
    output=_V("omega_a", "Wetting coefficient", "-", "dimensionless"),
    fn=lambda g13, g23, g12: (np.asarray(g13, float) - np.asarray(g23, float)) / np.asarray(g12, float),
    reference="Young's equation form used in Omranpour et al. (2025) SI",
    notes="ωa > 1 filler in phase 2; ωa < −1 filler in phase 1; in between it sits at the interface.",
    tags=("chemistry", "blend"),
))

# =============================================================================
# 7. Scattering & spectroscopy
# =============================================================================
_add(Equation(
    id="saxs_q_to_d",
    name="d-spacing from scattering vector",
    category="Scattering & spectroscopy",
    latex=r"d=\frac{2\pi}{q}",
    inputs=(_V("q", "Scattering vector q", "1/nm", "wavevector", 0.53, 1e-12),),
    output=_V("d", "d-spacing", "nm", "length"),
    fn=lambda q: 2.0 * math.pi / np.asarray(q, float),
    reference="Omranpour et al. (2024a) §3.3",
    tags=("saxs", "structure"),
))

_add(Equation(
    id="scattering_vector",
    name="Scattering vector from angle",
    category="Scattering & spectroscopy",
    latex=r"q=\frac{4\pi}{\lambda}\sin\theta",
    inputs=(
        _V("lambda_", "Wavelength", "Å", "length", 1.54, 1e-12),
        _V("theta", "Scattering half-angle θ", "deg", "angle", 0.5, 0),
    ),
    output=_V("q", "Scattering vector", "1/nm", "wavevector"),
    fn=lambda lambda_, theta: 4.0 * math.pi / (np.asarray(lambda_, float) * 0.1) * np.sin(np.radians(np.asarray(theta, float))),
    reference="Omranpour et al. (2024a) §2.4",
    tags=("saxs", "structure"),
))

_add(Equation(
    id="bragg_spacing",
    name="Bragg d-spacing from 2θ",
    category="Scattering & spectroscopy",
    latex=r"d=\frac{\lambda}{2\sin\theta}",
    inputs=(
        _V("lambda_", "Wavelength", "Å", "length", 1.5406, 1e-12),
        _V("two_theta", "2θ", "deg", "angle", 22.0, 1e-6),
    ),
    output=_V("d", "d-spacing", "nm", "length"),
    fn=lambda lambda_, two_theta: (np.asarray(lambda_, float) * 0.1) / (2.0 * np.sin(np.radians(np.asarray(two_theta, float) / 2.0))),
    reference="Bragg's law; Omranpour et al. (2024b) XRD",
    tags=("xrd", "structure"),
))

_add(Equation(
    id="scherrer_size",
    name="Crystallite size (Scherrer)",
    category="Scattering & spectroscopy",
    latex=r"D=\frac{K\lambda}{\beta\cos\theta}",
    inputs=(
        _V("K", "Shape factor K", "-", "dimensionless", 0.9, 0),
        _V("lambda_", "Wavelength", "Å", "length", 1.5406, 1e-12),
        _V("beta", "FWHM", "deg", "angle", 0.5, 1e-9),
        _V("two_theta", "2θ", "deg", "angle", 22.0),
    ),
    output=_V("D", "Crystallite size", "nm", "length"),
    fn=lambda K, lambda_, beta, two_theta: np.asarray(K, float) * (np.asarray(lambda_, float) * 0.1)
    / (np.radians(np.asarray(beta, float)) * np.cos(np.radians(np.asarray(two_theta, float) / 2.0))),
    reference="Scherrer equation",
    tags=("xrd", "structure"),
))

_add(Equation(
    id="long_period",
    name="Long period from SAXS peak",
    category="Scattering & spectroscopy",
    latex=r"L=\frac{2\pi}{q_{max}}",
    inputs=(_V("q_max", "Peak position q_max", "1/nm", "wavevector", 0.69, 1e-12),),
    output=_V("L", "Long period", "nm", "length"),
    fn=lambda q_max: 2.0 * math.pi / np.asarray(q_max, float),
    reference="Omranpour et al. (2024a) §3.3",
    tags=("saxs", "structure"),
))

# =============================================================================
# helpers used by the equations above
# =============================================================================
def _as_seq(value) -> np.ndarray:
    if isinstance(value, str):
        parts = [p for p in value.replace(";", ",").split(",") if p.strip()]
        return np.array([float(p) for p in parts], float)
    if isinstance(value, (list, tuple, np.ndarray)):
        return np.asarray(value, float)
    return np.asarray([float(value)], float)


def _rule_of_mixtures(w, rho):
    w_arr, rho_arr = _as_seq(w), _as_seq(rho)
    if w_arr.size != rho_arr.size:
        raise ValueError("skeletal_density_mixture: need one density per mass fraction")
    if np.any(rho_arr <= 0):
        raise ValueError("skeletal_density_mixture: densities must be positive")
    total = w_arr.sum()
    if total <= 0:
        raise ValueError("skeletal_density_mixture: mass fractions must sum to a positive number")
    frac = w_arr / total
    return float(1.0 / np.sum(frac / rho_arr))


def _halpin_tsai(E_m, E_f, phi_f, l_over_d):
    E_m = np.asarray(E_m, float)
    E_f = np.asarray(E_f, float)
    phi = np.asarray(phi_f, float)
    xi = 2.0 * np.asarray(l_over_d, float)
    ratio = E_f / E_m
    eta = (ratio - 1.0) / (ratio + xi)
    return E_m * (1.0 + xi * eta * phi) / (1.0 - eta * phi)


def _draw_ratio(V_takeup, Q, d_nozzle):
    area = math.pi * (np.asarray(d_nozzle, float) * 1e-6) ** 2 / 4.0
    v_exit = (np.asarray(Q, float) * 1e-6 / 3600.0) / area * 60.0  # m/min
    return np.asarray(V_takeup, float) / v_exit


def _k_model(k_s0, rho_b, rho_s, tau, D, beta, T, e_star):
    rho_b = np.asarray(rho_b, float)
    rho_s = np.asarray(rho_s, float)
    porosity = (1.0 - rho_b / rho_s) * 100.0
    k_solid = np.asarray(k_s0, float) * (rho_b / rho_s) ** np.asarray(tau, float)
    k_gas = K_AIR_STP * (porosity / 100.0) / (1.0 + 2.0 * np.asarray(beta, float) * MFP_AIR / np.asarray(D, float))
    k_rad = 16.0 * SIGMA_SB * (np.asarray(T, float) + 273.15) ** 3 / (3.0 * (np.asarray(e_star, float) * 1e3) * (rho_b * 1e3)) * 1e3
    return k_solid + k_gas + k_rad


def k_model_breakdown(k_s0, rho_b, rho_s, tau, D, beta, T, e_star) -> dict[str, float]:
    """Same model as `k_model_aerogel_fibre`, returning the three contributions separately."""
    rho_b_a = np.asarray(rho_b, float)
    rho_s_a = np.asarray(rho_s, float)
    porosity = (1.0 - rho_b_a / rho_s_a) * 100.0
    k_solid = float(np.asarray(k_s0, float) * (rho_b_a / rho_s_a) ** float(tau))
    k_gas = float(K_AIR_STP * (porosity / 100.0) / (1.0 + 2.0 * float(beta) * MFP_AIR / float(D)))
    k_rad = float(16.0 * SIGMA_SB * (float(T) + 273.15) ** 3 / (3.0 * (float(e_star) * 1e3) * (rho_b_a * 1e3)) * 1e3)
    return {"k_solid": k_solid, "k_gas": k_gas, "k_rad": k_rad, "k_total": k_solid + k_gas + k_rad,
            "porosity": float(porosity)}


# =============================================================================
# registry access
# =============================================================================
REGISTRY: dict[str, Equation] = _REG
CATEGORIES: tuple[str, ...] = (
    "Structure & porosity",
    "Thermal transport",
    "Mechanical",
    "Fatigue & durability",
    "Rheology & processing",
    "Chemistry & thermal analysis",
    "Scattering & spectroscopy",
)


def get(eq_id: str) -> Equation:
    try:
        return REGISTRY[eq_id]
    except KeyError as exc:
        raise KeyError(f"No equation with id {eq_id!r}. Known ids: {', '.join(sorted(REGISTRY))}") from exc


def by_category(category: str | None = None) -> dict[str, list[Equation]]:
    out: dict[str, list[Equation]] = {}
    for eq in REGISTRY.values():
        if category and eq.category != category:
            continue
        out.setdefault(eq.category, []).append(eq)
    for eqs in out.values():
        eqs.sort(key=lambda e: e.name)
    return {c: out[c] for c in CATEGORIES if c in out}


def search(query: str) -> list[Equation]:
    """Case-insensitive search over id, name, category, tags, symbols and reference."""
    q = (query or "").strip().lower()
    if not q:
        return sorted(REGISTRY.values(), key=lambda e: (e.category, e.name))
    hits: list[tuple[int, Equation]] = []
    for eq in REGISTRY.values():
        haystacks = [eq.name.lower(), eq.id.lower(), eq.category.lower(), eq.reference.lower(),
                     " ".join(eq.tags).lower(), " ".join(v.symbol.lower() for v in eq.inputs),
                     eq.output.symbol.lower(), eq.notes.lower()]
        score = 0
        for weight, hay in zip((100, 80, 30, 20, 40, 25, 25, 10), haystacks):
            if q in hay:
                score += weight + (25 if hay.startswith(q) else 0)
        if score:
            hits.append((score, eq))
    hits.sort(key=lambda t: (-t[0], t[1].name))
    return [eq for _, eq in hits]


def compute_many(eq_ids: Iterable[str], values: dict[str, float]) -> dict[str, float]:
    """Compute several equations from one pool of named values (used by batch mode)."""
    results: dict[str, float] = {}
    pool = dict(values)
    for eq_id in eq_ids:
        eq = get(eq_id)
        args = {v.symbol: pool.get(v.symbol) for v in eq.inputs}
        if any(a is None for a in args.values()):
            continue
        value = eq.compute(**args)
        results[eq.id] = value
        pool.setdefault(eq.output.symbol, value)
    return results
