"""Covariance-aware propagation and the Monte Carlo cross-check, against closed forms."""
from __future__ import annotations

import math

import numpy as np
import pytest

from aerolab.core import equations as E, uncertainty as U


def test_sum_with_correlation_matches_the_closed_form():
    """k_total = Σk: σ² = σ1² + σ2² + 2ρσ1σ2."""
    eq = E.get("k_total")
    values = {"k_solid": 5.0, "k_gas": 18.0, "k_rad": 3.0, "k_conv": 0.0}
    sig = {"k_solid": 0.5, "k_gas": 1.0}
    for rho in (-0.8, 0.0, 0.6, 1.0):
        r = U.propagate_linear(eq, values, sig, {"k_solid|k_gas": rho})
        assert r.sigma == pytest.approx(math.sqrt(0.25 + 1.0 + 2 * rho * 0.5 * 1.0), rel=1e-6)


def test_ratio_with_correlation_matches_the_closed_form():
    """r = a/b: (σr/r)² = (σa/a)² + (σb/b)² − 2ρ(σa/a)(σb/b)."""
    eq = E.get("relative_density")
    a, b, sa, sb, rho = 0.15, 1.116, 0.004, 0.02, 0.7
    r = U.propagate_linear(eq, {"rho_b": a, "rho_s": b}, {"rho_b": sa, "rho_s": sb}, {("rho_b", "rho_s"): rho})
    rel = math.sqrt((sa / a) ** 2 + (sb / b) ** 2 - 2 * rho * (sa / a) * (sb / b))
    assert r.sigma == pytest.approx(a / b * rel, rel=1e-6)
    assert r.correlated
    assert sum(r.contributions.values()) == pytest.approx(1.0, rel=1e-9)


def test_perfectly_correlated_ratio_of_equal_quantities_has_no_uncertainty():
    eq = E.get("relative_density")
    r = U.propagate_linear(eq, {"rho_b": 1.0, "rho_s": 1.0}, {"rho_b": 0.05, "rho_s": 0.05},
                           {"rho_b|rho_s": 1.0})
    assert r.sigma == pytest.approx(0.0, abs=1e-9)
    mc = U.monte_carlo(eq, {"rho_b": 1.0, "rho_s": 1.0}, {"rho_b": 0.05, "rho_s": 0.05},
                       {"rho_b|rho_s": 1.0}, n=2000)
    assert mc.sd == pytest.approx(0.0, abs=1e-9)          # singular R must still sample


def test_independent_case_matches_the_existing_first_order_method():
    eq = E.get("thermal_effusivity")
    values = {"k": 27.7, "rho": 0.1508, "c_p": 1000.0}
    sig = {"k": 0.8, "rho": 0.004, "c_p": 40.0}
    old = eq.compute_with_uncertainty(values, sig)
    new = U.propagate_linear(eq, values, sig)
    assert new.sigma == pytest.approx(old[1], rel=1e-9)
    # e ∝ (k ρ cp)^½ → relative σ is ½·√Σ(σi/xi)²
    rel = 0.5 * math.sqrt((0.8 / 27.7) ** 2 + (0.004 / 0.1508) ** 2 + (40 / 1000) ** 2)
    assert new.sigma == pytest.approx(new.value * rel, rel=1e-6)


@pytest.mark.parametrize("pairs,match", [
    ({"rho_b|rho_s": 1.2}, "between"),
    ({"rho_b|rho_b": 0.5}, "itself"),
])
def test_impossible_correlations_are_refused(pairs, match):
    eq = E.get("relative_density")
    with pytest.raises(ValueError, match=match):
        U.propagate_linear(eq, {"rho_b": 0.15, "rho_s": 1.1}, {"rho_b": 0.01, "rho_s": 0.01}, pairs)


def test_a_non_psd_matrix_is_refused():
    """r12 = r13 = 0.9 but r23 = −0.9 cannot all hold at once."""
    eq = E.get("k_total")
    values = {"k_solid": 5.0, "k_gas": 18.0, "k_rad": 3.0, "k_conv": 0.0}
    sig = {"k_solid": 0.5, "k_gas": 1.0, "k_rad": 0.3}
    with pytest.raises(ValueError, match="positive semi-definite"):
        U.propagate_linear(eq, values, sig, {"k_solid|k_gas": 0.9, "k_solid|k_rad": 0.9, "k_gas|k_rad": -0.9})


def test_monte_carlo_agrees_with_linear_for_small_sigma():
    eq = E.get("porosity_from_density")
    values, sig = {"rho_b": 0.211, "rho_s": 1.058}, {"rho_b": 0.002, "rho_s": 0.005}
    lin = U.propagate_linear(eq, values, sig, {"rho_b|rho_s": 0.3})
    mc = U.monte_carlo(eq, values, sig, {"rho_b|rho_s": 0.3}, n=40000, seed=3)
    assert mc.sd == pytest.approx(lin.sigma, rel=0.02)
    assert mc.mean == pytest.approx(lin.value, abs=0.05 * lin.sigma)
    assert U.compare(lin, mc)["agree"]


def test_monte_carlo_exposes_the_bias_of_1_over_x():
    """Kn = l/D with D = 30 ± 9 nm: E[1/D] > 1/E[D] (Jensen), so the linear σ is not enough."""
    eq = E.get("knudsen_number")
    values, sig = {"l_mfp": 70.0, "D": 30.0}, {"D": 9.0}
    lin = U.propagate_linear(eq, values, sig)
    mc = U.monte_carlo(eq, values, sig, n=40000, seed=1)
    assert lin.sigma == pytest.approx(70 / 30 * 0.3, rel=1e-6)
    assert mc.mean > lin.value * 1.05
    verdict = U.compare(lin, mc)
    assert not verdict["agree"] and "Monte Carlo 95 %" in verdict["message"]
    assert mc.rejected_fraction < 0.01              # D drawn ≤ 0 is rejected, and rare here


def test_monte_carlo_matches_a_lognormal_closed_form():
    """sqrt of a normal with small CV: E and SD known to second order; check the median."""
    eq = E.get("thermal_effusivity")
    values = {"k": 27.7, "rho": 0.1508, "c_p": 1000.0}
    mc = U.monte_carlo(eq, values, {"k": 0.277}, n=50000, seed=5)
    # e = C·√k: median of √k is √(median k) = √27.7 exactly for a symmetric k
    assert mc.median == pytest.approx(float(eq.compute(**values)), rel=1e-3)


def test_monte_carlo_is_reproducible_and_refuses_tiny_runs():
    eq = E.get("knudsen_number")
    a = U.monte_carlo(eq, {"l_mfp": 70.0, "D": 30.0}, {"D": 1.0}, n=500, seed=7)
    b = U.monte_carlo(eq, {"l_mfp": 70.0, "D": 30.0}, {"D": 1.0}, n=500, seed=7)
    assert a.mean == b.mean and a.low == b.low
    with pytest.raises(ValueError):
        U.monte_carlo(eq, {"l_mfp": 70.0, "D": 30.0}, {"D": 1.0}, n=10)


def test_monte_carlo_refuses_when_most_draws_leave_the_domain():
    eq = E.get("knudsen_number")
    with pytest.raises(ValueError, match="domain"):
        U.monte_carlo(eq, {"l_mfp": 70.0, "D": 1.0}, {"D": 50.0}, n=2000)


def test_zero_sigma_is_exact():
    eq = E.get("porosity_from_density")
    r = U.propagate_linear(eq, {"rho_b": 0.2, "rho_s": 1.0}, {"rho_b": 0.0})
    assert r.sigma == 0.0
    mc = U.monte_carlo(eq, {"rho_b": 0.2, "rho_s": 1.0}, {}, n=200)
    assert mc.sd == 0.0 and mc.mean == pytest.approx(80.0)


def test_derivative_failure_is_nan_not_zero():
    bad = E.Equation("t_bad", "bad", "test", "", (E._V("x", "x", "-"),), E._V("y", "y", "-"),
                     lambda x: 1.0 if x == 2.0 else float("nan"))
    r = U.propagate_linear(bad, {"x": 2.0}, {"x": 0.1})
    assert math.isnan(r.sigma)
