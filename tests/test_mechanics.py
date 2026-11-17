"""Mechanics studio: model recovery, comparisons, sensitivity and no extrapolation."""
from __future__ import annotations

import math

import numpy as np
import pytest

from aerolab.core import curves as C, mechanics as MX, measurements as M


# ------------------------------------------------------------------ modulus sensitivity
def test_linear_region_has_no_window_sensitivity():
    e = np.linspace(0, 40, 801)
    s = np.where(e <= 20, 0.5 * e, 10 + 0.05 * (e - 20))       # E = 50 MPa up to 20 %
    sens = MX.modulus_sensitivity(e, s)
    assert sens["cv_pct"] < 1e-6
    assert sens["mean"] == pytest.approx(50.0, rel=1e-9)


def test_a_curved_toe_shows_up_as_window_sensitivity():
    e = np.linspace(0, 40, 801)
    s = 2.0 * (e / 100) + 60.0 * (e / 100) ** 2               # stiffening, no linear region
    sens = MX.modulus_sensitivity(e, s)
    assert sens["cv_pct"] > 10
    r = C.analyze_stress_strain(e, s, offset_yield=0)
    assert r.value("Modulus window sensitivity") == pytest.approx(sens["cv_pct"])


# ------------------------------------------------------------------ S–N comparison
def test_basquin_data_prefers_basquin_and_bootstrap_brackets_the_truth():
    rng = np.random.default_rng(4)
    sa = np.repeat([3.0, 3.5, 4.0, 4.5, 5.0, 5.5], 3)
    two_n = (sa / 7.21) ** (1 / -0.063) * 10 ** rng.normal(0, 0.15, sa.size)
    r = MX.compare_sn_models(two_n / 2, sa, bootstrap=400, seed=1)
    assert r.meta["best"] == "basquin"
    lo, hi = r.meta["intervals"][("basquin", "b")]
    assert lo < -0.063 < hi
    gx, _gy = r.curves["Basquin σa = σ′f(2N)^b"]
    assert gx.min() == pytest.approx(two_n.min()) and gx.max() == pytest.approx(two_n.max())


def test_semilog_data_prefers_woehler():
    sa = np.linspace(2.0, 6.0, 12)
    log2n = 9.0 - 1.1 * sa                                  # exactly linear in stress
    r = MX.compare_sn_models(10 ** log2n / 2, sa, bootstrap=200)
    assert r.meta["best"] == "wohler"
    assert r.meta["fits"]["wohler"]["params"]["B"] == pytest.approx(-1 / 1.1, rel=1e-9)


def test_sn_comparison_refuses_degenerate_input():
    with pytest.raises(ValueError):
        MX.compare_sn_models([1000, 1000, 1000], [3, 4, 5])


def test_strain_life_bootstrap_intervals():
    rng = np.random.default_rng(2)
    two_n = np.logspace(2, 6, 10)
    ea = 0.4 * two_n ** -0.063 * 10 ** rng.normal(0, 0.01, 10)
    pa = 0.34 * two_n ** -0.14 * 10 ** rng.normal(0, 0.02, 10)
    ci = MX.strain_life_bootstrap(two_n / 2, ea, pa, bootstrap=400)
    for key, truth in (("b", -0.063), ("c", -0.14)):
        est, lo, hi = ci[key]
        assert lo <= est <= hi and lo < truth < hi


# ------------------------------------------------------------------ no extrapolation
def test_fatigue_fits_are_drawn_over_the_tested_range_only():
    two_n = np.array([2e2, 2e3, 2e4, 2e5])
    r = C.fit_sn_basquin(two_n / 2, 7.21 * two_n ** -0.063, life_at_fraction=0.2)
    gx, _ = r.curves["fit"]
    assert gx.min() == pytest.approx(2e2) and gx.max() == pytest.approx(2e5)
    # 20 % of σ'f is reached at N = 0.5·0.2^(1/b) ≈ 6e10 cycles, far beyond 1e5: flagged
    inside = C.fit_sn_basquin(two_n / 2, 7.21 * two_n ** -0.063, life_at_fraction=0.5)
    assert inside.meta["prediction_inside_range"] is True      # 0.5·0.5^(1/b) ≈ 3.0e4 cycles
    assert "OUTSIDE" in next(m.note for m in r.metrics if m.name.startswith("Predicted life"))
    assert r.meta["prediction_inside_range"] is False


# ------------------------------------------------------------------ cyclic energies
def test_cyclic_rows_carry_loading_and_unloading_energy():
    up = np.linspace(0, 0.5, 501)
    strain = np.concatenate([up, up[::-1][1:], up[1:], up[::-1][1:]]) * 100
    loop = np.concatenate([10 * up, 10 * up[::-1][1:] ** 2 / 0.5])
    stress = np.concatenate([loop, loop[1:]])
    r = C.analyze_cyclic_tension(strain, stress)
    row = r.meta["per_cycle"][0]
    assert row["loading_energy"] == pytest.approx(10 * 0.25 / 2, rel=1e-3)
    assert row["unloading_energy"] == pytest.approx(10 * 0.25 / 3, rel=1e-3)
    assert r.value("Cumulative dissipated energy") == pytest.approx(2 * 10 * 0.25 / 6, rel=2e-3)


# ------------------------------------------------------------------ viscoelastic models
def test_sls_relaxation_parameters_are_recovered_and_preferred():
    t = np.linspace(0.1, 400, 300)
    E = 2.0 + 3.0 * np.exp(-t / 40.0)
    fits = MX.fit_relaxation(t, E)
    best = fits[0]
    assert best.name in ("Standard linear solid", "Prony (2 terms)")
    sls = next(f for f in fits if f.name == "Standard linear solid")
    assert sls.params["E_inf"] == pytest.approx(2.0, rel=1e-4)
    assert sls.params["E1"] == pytest.approx(3.0, rel=1e-4)
    assert sls.params["tau"] == pytest.approx(40.0, rel=1e-4)
    maxwell = next(f for f in fits if f.name == "Maxwell")
    assert maxwell.aic > sls.aic                          # Maxwell cannot hold a plateau


def test_two_relaxation_times_need_prony():
    t = np.logspace(-1, 3, 200)
    E = 1.0 + 2.0 * np.exp(-t / 2.0) + 2.0 * np.exp(-t / 200.0)
    best = MX.fit_relaxation(t, E)[0]
    assert best.name == "Prony (2 terms)"
    taus = sorted([best.params["tau1"], best.params["tau2"]])
    assert taus[0] == pytest.approx(2.0, rel=1e-3) and taus[1] == pytest.approx(200.0, rel=1e-3)


def test_burgers_creep_is_recovered():
    t = np.linspace(0, 1800, 200)
    J = 0.2 + 0.1 * (1 - np.exp(-t / 120)) + 2e-5 * t
    fits = MX.fit_creep(t, J)
    assert fits[0].name == "Burgers"
    assert fits[0].params["1/eta"] == pytest.approx(2e-5, rel=1e-3)
    assert fits[0].params["tau"] == pytest.approx(120, rel=1e-3)


def test_kelvin_voigt_creep_is_recovered():
    t = np.linspace(0, 500, 120)
    J = 0.3 * (1 - np.exp(-t / 50))
    kv = next(f for f in MX.fit_creep(t, J) if f.name == "Kelvin–Voigt")
    assert kv.params["J_inf"] == pytest.approx(0.3, rel=1e-4)
    assert kv.params["tau"] == pytest.approx(50, rel=1e-4)


def test_viscoelastic_results_state_assumptions_and_stay_in_range():
    t = np.linspace(1, 300, 100)
    r = MX.analyze_relaxation(t, 0.05 * (2 + 3 * np.exp(-t / 40)), strain_pct=5.0)
    assert "Linear viscoelasticity" in r.metrics[0].note
    gx, _ = r.curves["fit"]
    assert gx.min() == pytest.approx(1) and gx.max() == pytest.approx(300)
    sls = next(f for f in r.meta["fits"] if f["name"] == "Standard linear solid")
    assert sls["params"]["E_inf"] == pytest.approx(2.0, rel=1e-4)   # modulus, not stress


def test_viscoelastic_input_guards():
    with pytest.raises(ValueError):
        MX.fit_creep([-1, 0, 1, 2, 3], [0, 1, 2, 3, 4])
    with pytest.raises(ValueError):
        MX.fit_relaxation([0, 1, 2, 3], [1, 1, 1, 1], models=["Nope"])
    with pytest.raises(ValueError):
        MX.analyze_creep(np.linspace(0, 10, 20), np.linspace(0, 1, 20), stress_mpa=-1.0)


def test_new_measurements_run_through_the_registry(samples_dir):
    from aerolab.io import readers as R
    for mid, opts in (("stress_relaxation", {"strain_pct": 5.0}), ("creep", {"stress_mpa": 0.5})):
        m = M.get(mid)
        ds = R.read_any(samples_dir / m.sample)[0]
        assert any("SYNTHETIC" in line for line in ds.meta.get("preamble", [])), "demo must say it is synthetic"
        mapping = m.match_columns(ds.headers)
        r = m.run({k: ds.columns[v] for k, v in mapping.items() if v is not None}, **opts)
        assert r.value("Best model (lowest AIC)") == 1.0
