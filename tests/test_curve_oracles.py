"""Recovery tests for the curve analysers on synthetic data with a known answer.

The truth is built from closed-form expressions (an exact BET isotherm, a Gaussian DSC
peak of known area, a logistic TGA step, analytic hysteresis loops) and the expected
numbers are derived on paper, never by running the analyser. Every analyser that
interpolates, differentiates or integrates along x is fed both axis orders, because
np.interp and np.gradient give silently wrong answers on decreasing x.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from aerolab.core import curves as C

AVOGADRO = 6.02214076e23          # exact (SI 2019)
N2_AREA = 0.162e-18               # m^2, the conventional N2 cross-section at 77 K
V_STP = 22414.0                   # cm^3/mol


def _both_orders(*arrays):
    yield arrays
    yield tuple(a[::-1] for a in arrays)


# ------------------------------------------------------------------ BET
@pytest.mark.parametrize("reverse", [False, True])
def test_bet_surface_area_from_an_exact_isotherm(reverse):
    vm, c = 80.0, 150.0
    x = np.linspace(0.04, 0.32, 15)
    v = vm * c * x / ((1 - x) * (1 - x + c * x))
    if reverse:                      # some instruments list the points high-to-low
        x, v = x[::-1], v[::-1]
    r = C.analyze_sorption_bet(x, v, bet_range=(0.05, 0.30))
    expected_s = vm / V_STP * AVOGADRO * N2_AREA       # m^2/g; = 348.2 for vm = 80
    assert expected_s == pytest.approx(348.2, rel=1e-3)
    assert r.value("BET surface area") == pytest.approx(expected_s, rel=1e-6)
    assert r.value("BET C constant") == pytest.approx(c, rel=1e-6)


def test_gurvich_pore_volume_uses_liquid_n2_density():
    """V_liquid = V_STP × (M_N2/ρ_liq)/V_m = V × 28.0134/0.808/22414 = V × 1.5468e-3."""
    x = np.concatenate([np.linspace(0.05, 0.30, 11), [0.5, 0.7, 0.9, 0.99]])
    vm, c = 60.0, 90.0
    v = vm * c * x / ((1 - x) * (1 - x + c * x))           # exact BET; 0.99 is a grid point
    r = C.analyze_sorption_bet(x, v)
    v_at = vm * c * 0.99 / (0.01 * (0.01 + c * 0.99))
    assert r.value("Total pore volume") == pytest.approx(v_at * 28.0134 / 0.808 / V_STP, rel=2e-3)


# ------------------------------------------------------------------ DSC
@pytest.mark.parametrize("reverse", [False, True])
def test_dsc_enthalpy_of_a_gaussian_peak_either_axis_order(reverse):
    T = np.linspace(100.0, 300.0, 1601)
    amp, width, tm, rate = 0.8, 6.0, 210.0, 20.0
    q = 0.05 - amp * np.exp(-((T - tm) / width) ** 2)
    if reverse:
        T, q = T[::-1], q[::-1]
    r = C.analyze_dsc(T, q, heating_rate=rate)
    # ∫ amp·exp(-(u/w)^2) du = amp·w·√π  (W/g·°C), divided by the rate in °C/s
    expected = amp * width * math.sqrt(math.pi) / (rate / 60.0)
    assert r.value("Endothermic peak (Tm)") == pytest.approx(tm, abs=0.2)
    assert r.value("Melting enthalpy ΔHm") == pytest.approx(expected, rel=0.02)


def test_dsc_mw_signal_with_sample_mass_gives_w_per_g():
    T = np.linspace(100.0, 300.0, 1601)
    mass = 5.0                                         # mg
    q_mw = -mass * 0.4 * np.exp(-((T - 200.0) / 5.0) ** 2)   # mW
    r = C.analyze_dsc(T, q_mw, heating_rate=10.0, sample_mass_mg=mass)
    expected = 0.4 * 5.0 * math.sqrt(math.pi) / (10.0 / 60.0)   # J/g
    assert r.value("Melting enthalpy ΔHm") == pytest.approx(expected, rel=0.02)


# ------------------------------------------------------------------ TGA
@pytest.mark.parametrize("reverse", [False, True])
def test_tga_logistic_step_threshold_temperatures(reverse):
    T = np.linspace(30.0, 700.0, 2000)
    t0, s, drop = 400.0, 12.0, 60.0
    w = 100.0 - drop / (1.0 + np.exp(-(T - t0) / s))
    if reverse:
        T, w = T[::-1], w[::-1]
    r = C.analyze_tga(T, w, thresholds=(5.0, 30.0))
    # loss(T) = drop·σ((T−t0)/s) (w0 ≈ 100). loss = 30 at T = t0; loss = 5 when σ = 1/12,
    # i.e. T = t0 − s·ln 11. The first point is not exactly 100, so allow 0.1 °C.
    w0 = 100.0 - drop / (1.0 + math.exp(-(30.0 - t0) / s))
    t5 = t0 - s * math.log(drop / (5.0 * w0 / 100.0) - 1.0)
    assert r.value("T at 5 % loss") == pytest.approx(t5, abs=0.1)
    assert r.value("T at 30 % loss") == pytest.approx(t0, abs=0.1)
    assert r.value("DTG peak 1") == pytest.approx(t0, abs=1.0)
    assert r.value("Residue at final temperature") == pytest.approx(40.0, abs=0.01)


# ------------------------------------------------------------------ cyclic tension
def test_hysteresis_energy_of_an_analytic_loop():
    """Load σ = Eε, unload σ = Eε²/ε_max: W_load = Eε²/2, W_unload = Eε²/3, so ΔW = Eε²/6."""
    E_mod, eps_max = 10.0, 0.5                # MPa, strain as a fraction (50 %)
    up = np.linspace(0, eps_max, 2001)
    down = up[::-1][1:]
    strain = np.concatenate([up, down])
    stress = np.concatenate([E_mod * up, E_mod * down ** 2 / eps_max])
    # two identical cycles so there is a "last cycle" too
    strain2 = np.concatenate([strain, strain[1:]]) * 100.0
    stress2 = np.concatenate([stress, stress[1:]])
    r = C.analyze_cyclic_tension(strain2, stress2)
    expected = E_mod * eps_max ** 2 / 6.0     # MJ/m^3
    assert r.value("Cycles detected") == 2
    assert r.value("Hysteresis energy, cycle 1") == pytest.approx(expected, rel=1e-3)
    row = r.meta["per_cycle"][0]
    assert row["dissipation_ratio"] == pytest.approx(100.0 / 3.0, rel=1e-3)
    assert row["permanent_set"] == pytest.approx(0.0, abs=0.2)


# ------------------------------------------------------------------ tensile
def test_toughness_of_an_elastic_perfectly_plastic_curve():
    """E = 100 MPa to yield at 2 % (σy = 2 MPa), flat to 50 %: area = ½·0.02·2 + 0.48·2."""
    e = np.linspace(0, 50, 5001)
    s = np.minimum(100.0 * e / 100.0, 2.0)
    r = C.analyze_stress_strain(e, s, offset_yield=0)
    assert r.value("Young's modulus") == pytest.approx(100.0, rel=1e-6)
    assert r.value("Toughness") == pytest.approx(0.5 * 0.02 * 2.0 + 0.48 * 2.0, rel=1e-4)


@pytest.mark.parametrize("reverse", [False, True])
def test_stress_strain_accepts_either_order(reverse):
    e = np.linspace(0, 20, 401)
    x = e / 100.0
    s = np.where(x <= 0.02, 30.0 * x, 0.6 + 30.0 * (x - 0.02) - 60.0 * (x - 0.02) ** 2)
    if reverse:
        e, s = e[::-1], s[::-1]
    r = C.analyze_stress_strain(e, s, modulus_range=(0.0, 1.0), offset_yield=0)
    assert r.value("Young's modulus") == pytest.approx(30.0, rel=0.01)


# ------------------------------------------------------------------ rheology
@pytest.mark.parametrize("reverse", [False, True])
def test_crossover_point_and_modulus_on_power_laws(reverse):
    """G′ = 2e4·x^-0.5, G″ = 50·x^0.4 cross at x* = 400^(1/0.9); the modulus there is 2e4·x*^-0.5."""
    x = np.logspace(0, 5, 41)
    gp, gpp = 2e4 * x ** -0.5, 50.0 * x ** 0.4
    x_star = 400.0 ** (1 / 0.9)
    g_star = 2e4 * x_star ** -0.5
    if reverse:
        x, gp, gpp = x[::-1], gp[::-1], gpp[::-1]
    r = C.find_moduli_crossover(x, gp, gpp)
    assert r.value("Flow point (G′ = G″)") == pytest.approx(x_star, rel=1e-9)
    # power laws are straight lines in log-log space, so log interpolation is exact
    assert r.value("Modulus at crossover") == pytest.approx(g_star, rel=1e-9)


def test_herschel_bulkley_recovers_parameters_in_reverse_order():
    g = np.logspace(-1, 2, 30)[::-1]
    r = C.fit_herschel_bulkley(g, 120.0 + 8.0 * g ** 0.6)
    assert r.value("Yield stress τy") == pytest.approx(120.0, rel=1e-4)
    assert r.value("Flow index n") == pytest.approx(0.6, rel=1e-4)


# ------------------------------------------------------------------ fatigue
def test_basquin_exact_data_recovers_constants_and_life_prediction():
    two_n = np.array([2e2, 2e3, 2e4, 2e5, 2e6])
    sf, b = 7.21, -0.063
    sa = sf * two_n ** b
    r = C.fit_sn_basquin(two_n / 2.0, sa, life_at_fraction=0.5)
    assert r.value("Fatigue strength coefficient σ'f") == pytest.approx(sf, rel=1e-9)
    assert r.value("Fatigue strength exponent b") == pytest.approx(b, rel=1e-9)
    # σa = 0.5 σf  ->  2N = 0.5^(1/b)  ->  N = 0.5·0.5^(1/b)
    assert r.value("Predicted life at 50 % of σ'f") == pytest.approx(0.5 * 0.5 ** (1 / b), rel=1e-9)


def test_thermal_point_derived_properties():
    r = C.analyze_thermal_point(30.0, 0.12, 1300.0, thickness_mm=4.0)
    assert r.value("Thermal diffusivity") == pytest.approx(0.030 / (120.0 * 1300.0) * 1e6, rel=1e-12)
    assert r.value("Thermal effusivity") == pytest.approx(math.sqrt(0.030 * 120.0 * 1300.0), rel=1e-12)
    assert r.value("Volumetric heat capacity") == pytest.approx(0.156, rel=1e-12)
    assert r.value("R-value") == pytest.approx(0.004 / 0.030, rel=1e-12)
    assert r.value("Clo value") == pytest.approx(0.004 / 0.030 / 0.155, rel=1e-12)
