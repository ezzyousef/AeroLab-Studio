"""Materials studio: recovery on synthetic curves with known answers, and QC rules."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from aerolab.core import curves as C, materials as MT, workspace as W


def _two_step_tga(reverse=False):
    T = np.linspace(30, 800, 3000)
    w = 100 - 20 / (1 + np.exp(-(T - 300) / 10)) - 40 / (1 + np.exp(-(T - 480) / 12))
    return (T[::-1], w[::-1]) if reverse else (T, w)


@pytest.mark.parametrize("reverse", [False, True])
def test_tga_steps_recover_each_mass_loss(reverse):
    T, w = _two_step_tga(reverse)
    steps = MT.tga_steps(T, w)
    assert len(steps) == 2
    assert steps[0]["peak"] == pytest.approx(300, abs=1.5)
    assert steps[1]["peak"] == pytest.approx(480, abs=1.5)
    assert steps[0]["loss"] == pytest.approx(20, abs=0.3)
    assert steps[1]["loss"] == pytest.approx(40, abs=0.3)
    # steps partition the curve, so their losses add up to the total exactly
    assert sum(s["loss"] for s in steps) == pytest.approx(max(w) - min(w), abs=1e-6)
    r = C.analyze_tga(T, w)
    assert r.value("Decomposition steps") == 2
    assert r.value("Step 2 mass loss") == pytest.approx(40, abs=0.3)


def test_dsc_event_table_crystallinity_needs_dh100():
    tr = [{"kind": "endotherm", "T": 170.0, "enthalpy": 9.84, "onset": 150.0, "end": 185.0},
          {"kind": "exotherm", "T": 90.0, "enthalpy": 3.0, "onset": 80.0, "end": 100.0}]
    rows = MT.dsc_event_table(tr)
    assert [r["kind"] for r in rows] == ["exotherm", "endotherm"]
    assert all(math.isnan(r["crystallinity"]) for r in rows)
    rows = MT.dsc_event_table(tr, polymer_fraction=0.5, dh100=196.8)
    endo = rows[1]
    assert endo["enthalpy_per_polymer"] == pytest.approx(19.68)
    assert endo["crystallinity"] == pytest.approx(9.84 / (0.5 * 196.8) * 100)
    with pytest.raises(ValueError):
        MT.dsc_event_table(tr, polymer_fraction=1.5)


def test_k_vs_density_finds_a_minimum_only_inside_the_range():
    rho = np.linspace(0.05, 0.25, 9)
    k = 18 + 400 * (rho - 0.12) ** 2                          # minimum at 0.12 g/cm^3
    r = MT.fit_k_vs_density(rho, k)
    assert r.meta["best"] == "quadratic"
    assert r.value("Density of minimum k (quadratic)") == pytest.approx(0.12, rel=1e-9)
    r2 = MT.fit_k_vs_density(rho[rho > 0.15], k[rho > 0.15])   # only the rising branch
    assert math.isnan(r2.value("Density of minimum k (quadratic)"))
    gx, _ = r.curves["quadratic fit"]
    assert gx.min() == pytest.approx(0.05) and gx.max() == pytest.approx(0.25)


def test_k_vs_density_power_law_recovery():
    rho = np.linspace(0.1, 0.3, 8)
    r = MT.fit_k_vs_density(rho, 60 * rho ** 0.5)
    assert r.value("Power-law exponent") == pytest.approx(0.5, rel=1e-9)


def test_porosity_summary_against_hand_values():
    out = MT.porosity_summary(350.15, 1.2, 0.211, 1.058)
    vp = 1 / 0.211 - 1 / 1.058                               # 3.794 cm^3/g
    assert out["Pore volume, densities"]["value"] == pytest.approx(vp)
    assert out["Mean pore diameter, densities"]["value"] == pytest.approx(4 * vp * 1e-6 / 350.15 * 1e9)
    assert out["Pore volume seen by N₂"]["value"] == pytest.approx(1.2 / vp * 100)
    assert out["Mean pore diameter, N₂"]["value"] == pytest.approx(4 * 1.2e-6 / 350.15 * 1e9)


@pytest.mark.parametrize("reverse", [False, True])
def test_lver_limit_on_a_known_softening_curve(reverse):
    x = np.logspace(-1, 3, 81)
    gp = 1000.0 / (1 + (x / 50.0) ** 2)                       # G' = 900 at x = 50/3 exactly
    if reverse:
        x, gp = x[::-1], gp[::-1]
    lv = MT.lver_limit(x, gp, tolerance=0.1, plateau_points=5)
    # plateau = median of the 5 lowest-amplitude points; solve 1000/(1 + (x/50)²) = 0.9·plateau
    plateau = float(np.median(1000.0 / (1 + (np.logspace(-1, 3, 81)[:5] / 50.0) ** 2)))
    expected = 50.0 * math.sqrt(1000.0 / (0.9 * plateau) - 1)
    assert lv["limit"] == pytest.approx(expected, rel=0.01)


def test_crossover_reports_the_lver():
    x = np.logspace(-1, 3, 81)
    gp = 1000.0 / (1 + (x / 50.0) ** 2)
    gpp = 100.0 * (1 + x / 50.0)
    r = C.find_moduli_crossover(x, gp, gpp)
    assert math.isfinite(r.value("End of linear viscoelastic region"))


# ------------------------------------------------------------------ QC
def _exp(cal="2026-01-10", date_="2026-06-01"):
    return W.Experiment("E1", "S1", "dsc", W.Instrument("DSC 2500", calibration_date=cal), date=date_)


def test_qc_flags_missing_and_stale_calibration():
    r = C.AnalysisResult("dsc", [C.Metric("Transitions found", 1.0)], {}, {})
    assert any("Not linked" in m for _l, m in MT.qc_flags("dsc", r))
    assert any("not recorded" in m for _l, m in MT.qc_flags("dsc", r, experiment=_exp(cal="")))
    stale = MT.qc_flags("dsc", r, {"heating_rate": 10}, experiment=_exp(cal="2025-01-01", date_="2026-06-01"))
    assert any("days old" in m for _l, m in stale)
    fresh = MT.qc_flags("dsc", r, {"heating_rate": 10}, experiment=_exp())
    assert fresh == []
    future = MT.qc_flags("dsc", r, {"heating_rate": 10}, experiment=_exp(cal="2026-07-01"))
    assert any("after the test" in m for _l, m in future)


def test_qc_flags_moisture_in_tga_and_bad_bet():
    T = np.linspace(30, 600, 400)
    w = 100 - 3 / (1 + np.exp(-(T - 80) / 8)) - 50 / (1 + np.exp(-(T - 400) / 10))
    r = C.analyze_tga(T, w)
    assert any("below 150" in m for _l, m in MT.qc_flags("tga", r, experiment=_exp()))
    assert not any("below 150" in m for _l, m in MT.qc_flags("tga", r, {"dry_basis_at": 150}, experiment=_exp()))
    bet = C.AnalysisResult("sorption", [C.Metric("BET C constant", 1.2), C.Metric("Total pore volume", 0.5)], {},
                           {"criteria_problems": ["C ≤ 0"]})
    msgs = [m for _l, m in MT.qc_flags("sorption", bet, experiment=_exp())]
    assert any("outside 2–1000" in m for m in msgs) and any("C ≤ 0" in m for m in msgs)


def test_qc_flags_window_sensitive_modulus_and_sample_without_density():
    e = np.linspace(0, 40, 801)
    r = C.analyze_stress_strain(e, 2.0 * (e / 100) + 60.0 * (e / 100) ** 2, offset_yield=0)
    msgs = [m for _l, m in MT.qc_flags("stress_strain", r, experiment=_exp(), sample=W.Sample("S1"))]
    assert any("varies by" in m for m in msgs)
    assert any("no bulk density" in m for m in msgs)
