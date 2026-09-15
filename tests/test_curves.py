"""The analysers, against synthetic data whose answers are known exactly."""
from __future__ import annotations

import math

import numpy as np
import pytest

from aerolab.core import curves as C


# ------------------------------------------------------------------ stress-strain
def test_stress_strain_recovers_the_modulus():
    e = np.linspace(0, 188, 400)
    s = np.where(e < 8, 20.0 * e / 100.0, 1.6 + 11.0 * np.tanh((e - 8) / 90.0))
    s[-1] *= 0.999
    r = C.analyze_stress_strain(e, s)
    assert r.value("Young's modulus") == pytest.approx(20.0, rel=0.06)
    assert r.value("Ultimate tensile strength") == pytest.approx(float(s.max()), rel=1e-9)
    assert r.value("Elongation at break") == pytest.approx(188.0, rel=1e-9)
    assert r.value("Toughness") == pytest.approx(float(np.trapezoid(s, e / 100)), rel=1e-9)


def test_stress_strain_modulus_ignores_a_toe_region():
    """A slack grip gives a shallow toe; the fit must find the real slope after it."""
    e = np.linspace(0, 120, 600)
    s = np.where(e < 5, 0.4 * e / 100, 0.02 + 18.0 * (e - 5) / 100)
    r = C.analyze_stress_strain(e, s)
    assert r.value("Young's modulus") == pytest.approx(18.0, rel=0.08)


# ------------------------------------------------------------------------- cyclic
def _cyclic(sets=(5.0, 8.0, 11.0), peak=100.0, stress=9.85):
    strain, stresses = [], []
    for i, ps in enumerate(sets):
        start = sets[i - 1] if i else 0.0
        up = np.linspace(start, peak, 120)
        strain += list(up)
        stresses += list(stress * ((up - start) / (peak - start)) ** 1.6)
        down = np.linspace(peak, ps, 120)
        strain += list(down)
        stresses += list(stress * np.clip((down - ps) / (peak - ps), 0, None) ** 2.6)
    return np.array(strain), np.array(stresses)


def test_cyclic_finds_every_cycle_and_its_permanent_set():
    r = C.analyze_cyclic_tension(*_cyclic())
    assert r.value("Cycles detected") == 3
    assert r.value("Permanent set, cycle 1") == pytest.approx(5.0, rel=0.02)
    assert r.value("Permanent set, last cycle") == pytest.approx(11.0, rel=0.02)
    assert r.value("ER/εmax, cycle 1") == pytest.approx(95.0, rel=0.02)
    assert r.value("Hysteresis energy, cycle 1") > 0
    assert len(r.curves) == 3


def test_cyclic_permanent_set_survives_a_load_cell_noise_floor():
    """Below the noise floor the stress reads zero early; the set must not drift with it."""
    strain, stress = _cyclic()
    rng = np.random.default_rng(7)
    noisy = np.clip(stress + rng.normal(0, 0.004, stress.size), 0, None)
    r = C.analyze_cyclic_tension(strain, noisy)
    assert r.value("Permanent set, cycle 1") == pytest.approx(5.0, abs=0.3)


# ------------------------------------------------------------------------ fatigue
def test_basquin_fit():
    N = np.array([10, 50, 200, 1000, 5000, 20000], float)
    r = C.fit_sn_basquin(N, 7.21 * (2 * N) ** -0.063)
    assert r.value("Fatigue strength coefficient σ'f") == pytest.approx(7.21, rel=1e-3)
    assert r.value("Fatigue strength exponent b") == pytest.approx(-0.063, rel=1e-3)
    assert r.value("R²") > 0.999


def test_strain_life_fit_and_transition():
    N = np.array([10, 50, 200, 1000, 5000, 20000], float)
    r = C.fit_strain_life(N, (7.21 / 18.0) * (2 * N) ** -0.063, 0.34 * (2 * N) ** -0.14,
                          modulus=18.0)
    assert r.value("Fatigue strength exponent b") == pytest.approx(-0.063, rel=1e-3)
    assert r.value("Fatigue ductility exponent c") == pytest.approx(-0.14, rel=1e-3)
    assert r.value("Fatigue ductility coefficient ε'f") == pytest.approx(0.34, rel=1e-3)
    assert r.value("Fatigue strength coefficient σ'f") == pytest.approx(7.21, rel=1e-3)
    expected = (0.34 * 18 / 7.21) ** (1 / (-0.063 + 0.14))
    assert r.value("Transition life 2Nt") == pytest.approx(expected, rel=0.02)


def test_strain_life_omits_sigma_f_without_a_modulus():
    N = np.array([10, 50, 200, 1000, 5000, 20000], float)
    r = C.fit_strain_life(N, 0.4 * (2 * N) ** -0.063, 0.34 * (2 * N) ** -0.14)
    assert r.value("Fatigue strength coefficient σ'f") is None


# ---------------------------------------------------------------------------- TGA
def test_tga_thresholds_and_residue():
    T = np.linspace(30, 800, 800)
    w = 29 + 71 / (1 + np.exp((T - 420) / 18.0))
    r = C.analyze_tga(T, w)
    expected_50 = 420 + 18 * math.log(71 / 21 - 1)      # 50 points of loss, not 50 %
    assert r.value("T at 50 % loss") == pytest.approx(expected_50, rel=0.01)
    assert r.value("Residue at final temperature") == pytest.approx(float(w[-1]), rel=1e-9)
    assert r.value("DTG peak 1") == pytest.approx(420.0, rel=0.02)


# ---------------------------------------------------------------------------- DSC
def test_dsc_single_peak_enthalpy():
    T = np.linspace(150, 300, 600)
    A, width, Tm = 0.5, 5.0, 232.0
    q = -A * np.exp(-((T - Tm) / width) ** 2)
    r = C.analyze_dsc(T, q, heating_rate=10.0)
    assert r.value("Endothermic peak (Tm)") == pytest.approx(Tm, rel=1e-3)
    expected = A * width * math.sqrt(math.pi) / (10.0 / 60.0)
    assert r.value("Melting enthalpy ΔHm") == pytest.approx(expected, rel=0.05)


def test_dsc_separates_two_melts_on_a_glass_transition_step():
    """The hard case: two endotherms, a cold-crystallisation exotherm and a Tg step."""
    T = np.linspace(-60, 260, 1400)
    q = (-0.42 * np.exp(-((T - 172.0) / 11.0) ** 2)
         - 0.55 * np.exp(-((T - 214.0) / 7.5) ** 2)
         + 0.30 * np.exp(-((T - 92.0) / 9.0) ** 2)
         + 0.055 / (1 + np.exp(-(T + 32.0) / 4.0)) - 0.10 + 3.2e-4 * T)
    r = C.analyze_dsc(T, q, heating_rate=10.0)
    transitions = r.meta["transitions"]
    assert r.value("Transitions found") == 3, "the rise between two melts is not an exotherm"
    assert [t["kind"] for t in transitions] == ["exotherm", "endotherm", "endotherm"]

    k = 6 * math.sqrt(math.pi)                          # amplitude x width x sqrt(pi) / rate
    assert transitions[0]["T"] == pytest.approx(92.0, rel=0.01)
    assert transitions[0]["enthalpy"] == pytest.approx(0.30 * 9 * k, rel=0.05)
    assert transitions[1]["T"] == pytest.approx(172.0, rel=0.01)
    assert transitions[1]["enthalpy"] == pytest.approx(0.42 * 11 * k, rel=0.05)
    assert transitions[2]["enthalpy"] == pytest.approx(0.55 * 7.5 * k, rel=0.05)
    assert r.value("Glass transition estimate") == pytest.approx(-32.0, rel=0.1)


# ---------------------------------------------------------------------------- BET
def test_bet_recovers_monolayer_volume_and_c():
    x = np.linspace(0.03, 0.99, 60)
    Vm, Cc = 100.0, 100.0
    V = Vm * Cc * x / ((1 - x) * (1 + (Cc - 1) * x))
    r = C.analyze_sorption_bet(x, V)
    assert r.value("Monolayer volume Vm") == pytest.approx(Vm, rel=0.02)
    assert r.value("BET C constant") == pytest.approx(Cc, rel=0.05)
    assert r.value("BET surface area") == pytest.approx(Vm * 4.3526, rel=0.02)
    assert r.value("BET fit R²") > 0.999


# ----------------------------------------------------------------------- rheology
def test_herschel_bulkley_fit():
    g = np.logspace(-2, 1, 40)
    r = C.fit_herschel_bulkley(g, 6000 + 120 * g ** 0.45)
    assert r.value("Yield stress τy") == pytest.approx(6000.0, rel=1e-3)
    assert r.value("Consistency index K") == pytest.approx(120.0, rel=0.02)
    assert r.value("Flow index n") == pytest.approx(0.45, rel=0.02)


def test_crossover_is_found_by_interpolation():
    x = np.logspace(1, 4, 60)
    gp = 30000 / (1 + (x / 2000) ** 2.0)
    r = C.find_moduli_crossover(x, gp, gp * (x / 2000))
    assert r.value("Flow point (G′ = G″)") == pytest.approx(2000.0, rel=0.03)


def test_power_law_scaling():
    rho = np.linspace(0.132, 0.157, 8)
    r = C.fit_power_law_scaling(rho, 14.12 * (rho / 1.116) ** 0.78, rho_solid=1.116)
    assert r.value("Scaling exponent n") == pytest.approx(0.78, rel=1e-3)
    assert r.value("Density span") == pytest.approx(0.157 / 0.132, rel=1e-9)


# ------------------------------------------------------------------------- guards
def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError):
        C.analyze_stress_strain([0, 1, 2], [0, 1])


def test_too_few_points_are_rejected():
    with pytest.raises(ValueError):
        C.analyze_stress_strain([0, 1], [0, 1])


def test_nan_rows_are_dropped_not_propagated():
    e = np.linspace(0, 100, 200)
    s = 15.0 * e / 100
    s[50] = np.nan
    r = C.analyze_stress_strain(e, s)
    assert math.isfinite(r.value("Young's modulus"))


def test_every_analyser_is_registered():
    from aerolab.core.measurements import MEASUREMENTS
    for measurement in MEASUREMENTS:
        assert callable(measurement.analyser), measurement.id


def test_degenerate_fits_are_refused_not_returned_as_nan():
    """A fit with no variance in x has no answer; saying so beats returning NaN."""
    with pytest.raises(ValueError, match="same life"):
        C.fit_sn_basquin(np.full(6, 100.0), np.linspace(5, 4, 6))
    with pytest.raises(ValueError, match="same"):
        C.fit_power_law_scaling(np.full(6, 0.15), np.linspace(10, 12, 6))


@pytest.mark.parametrize("name,call", [
    ("stress-strain on a flat trace", lambda: C.analyze_stress_strain(
        np.linspace(0, 100, 50), np.ones(50))),
    ("TGA with no mass loss", lambda: C.analyze_tga(
        np.linspace(30, 800, 50), np.full(50, 100.0))),
    ("DSC with no peaks", lambda: C.analyze_dsc(np.linspace(0, 300, 60), np.ones(60))),
    ("a sweep whose moduli never cross", lambda: C.find_moduli_crossover(
        np.logspace(0, 3, 20), np.full(20, 1000.0), np.full(20, 10.0))),
    ("a monotonic pull sent to the cyclic analyser", lambda: C.analyze_cyclic_tension(
        np.linspace(0, 100, 50), np.linspace(0, 10, 50))),
])
def test_degenerate_input_never_crashes(name, call):
    """Either a clear refusal or a result whose unavailable numbers are NaN, never a crash."""
    try:
        result = call()
    except ValueError:
        return                                  # a clear refusal is a correct outcome
    assert result.metrics, name
    for metric in result.metrics:               # NaN is allowed; anything unprintable is not
        assert isinstance(metric.value, float), f"{name}: {metric.name}"
