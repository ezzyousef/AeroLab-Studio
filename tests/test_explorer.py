"""Experiment explorer: statistics, response surface, sensitivity, π groups, DOE, export checks."""
from __future__ import annotations

import math

import numpy as np
import pytest

from aerolab.core import equations as E, explorer as X


# ------------------------------------------------------------------ statistics
def test_welch_matches_a_hand_calculation():
    a, b = [10.0, 12.0, 11.0, 13.0], [8.0, 9.0, 7.5]
    r = X.welch_t_test(a, b)
    ma, mb = np.mean(a), np.mean(b)
    va, vb = np.var(a, ddof=1) / 4, np.var(b, ddof=1) / 3
    assert r["t"] == pytest.approx((ma - mb) / math.sqrt(va + vb))
    assert r["df"] == pytest.approx((va + vb) ** 2 / (va ** 2 / 3 + vb ** 2 / 2))
    assert 0 < r["p"] < 0.05
    assert math.isnan(X.welch_t_test([1.0], [2.0, 3.0])["p"])


def test_anova_detects_a_shifted_group():
    r = X.one_way_anova({"A": [1, 1.1, 0.9], "B": [1.05, 0.95, 1.0], "C": [2.0, 2.1, 1.9]})
    assert r["p"] < 1e-3 and r["groups"] == 3


def test_normalised_comparison_uses_specific_values():
    rows = [{"sample": "ref", "value": 10.0, "density": 0.20},
            {"sample": "light", "value": 6.0, "density": 0.10},
            {"sample": "unknown density", "value": 8.0}]
    out = {r["sample"]: r for r in X.normalised_comparison(rows, "ref")}
    assert out["light"]["relative"] == pytest.approx(0.6)
    assert out["light"]["specific_relative"] == pytest.approx((6 / 0.1) / (10 / 0.2))
    assert math.isnan(out["unknown density"]["specific"])          # never guessed
    with pytest.raises(ValueError):
        X.normalised_comparison(rows, "missing")


# ------------------------------------------------------------------ response surface
def test_response_surface_recovers_an_exact_quadratic_and_its_minimum():
    g = np.array([-1.0, 0.0, 1.0])
    x1, x2 = (a.ravel() for a in np.meshgrid(g * 0.05 + 0.15, g * 2 + 6))
    y = 30 + 200 * (x1 - 0.14) ** 2 + 0.5 * (x2 - 6.5) ** 2 + 3 * (x1 - 0.14) * (x2 - 6.5)
    rs = X.response_surface(x1, x2, y)
    assert rs["r2"] == pytest.approx(1.0)
    assert rs["stationary_kind"] == "minimum" and rs["stationary_inside"]
    assert rs["stationary"][0] == pytest.approx(0.14, rel=1e-6)
    assert rs["stationary"][1] == pytest.approx(6.5, rel=1e-6)
    assert rs["stationary"][2] == pytest.approx(30.0, rel=1e-9)
    G1, G2, _Z = rs["grid"]
    assert G1.min() == pytest.approx(x1.min()) and G2.max() == pytest.approx(x2.max())


def test_response_surface_refuses_too_few_runs_or_two_levels():
    with pytest.raises(ValueError, match="at least 7"):
        X.response_surface([1, 2, 3], [1, 2, 3], [1, 2, 3])
    x1, x2 = (a.ravel() for a in np.meshgrid([0, 1], [0, 1, 2, 3]))
    with pytest.raises(ValueError, match="three or more levels"):
        X.response_surface(x1, x2, x1 + x2)


# ------------------------------------------------------------------ sensitivity
def test_elasticities_of_power_laws_are_their_exponents():
    el = X.elasticities(E.get("thermal_effusivity"), {"k": 27.7, "rho": 0.15, "c_p": 1000.0})
    assert all(v == pytest.approx(0.5, rel=1e-5) for v in el.values())
    el = X.elasticities(E.get("euler_buckling"), {"E": 3.51, "D": 90.0, "L": 10.0, "K": 1.0})
    assert el["D"] == pytest.approx(4.0, rel=1e-5) and el["L"] == pytest.approx(-2.0, rel=1e-5)


# ------------------------------------------------------------------ dimensional analysis
def test_capillary_number_is_the_single_pi_group():
    da = X.dimensional_analysis(E.get("capillary_number"))
    # inputs η, γ̇, R, Γ and the output Ca (dimensionless, itself a group)
    assert da["rank"] == 3 and da["n_groups"] == 2
    exps = [g["exponents"] for g in da["groups"]]
    ca = next(e for e in exps if "eta_m" in e)
    ratio = {k: float(__import__("fractions").Fraction(v)) / float(__import__("fractions").Fraction(ca["eta_m"]))
             for k, v in ca.items()}
    assert ratio == {"eta_m": 1.0, "gamma_dot": 1.0, "R": 1.0, "Gamma": -1.0}


def test_effusivity_needs_fractional_exponents():
    da = X.dimensional_analysis(E.get("thermal_effusivity"))
    # k, ρ, cp, e: e² = k ρ cp, so one group e·(kρcp)^(-1/2), written with integers as e²/(kρcp)
    assert da["n_groups"] == 1
    g = {k: int(v) for k, v in da["groups"][0]["exponents"].items()}
    scale = g["e"] // 2 if g["e"] % 2 == 0 else 1
    assert {k: v / scale for k, v in g.items()} in ({"k": -1, "rho": -1, "c_p": -1, "e": 2},
                                                     {"k": 1, "rho": 1, "c_p": 1, "e": -2})


def test_dimensional_analysis_excludes_unfixed_units():
    da = X.dimensional_analysis(E.get("herschel_bulkley"))
    assert "K" in da["excluded"]


# ------------------------------------------------------------------ DOE
def test_designs_have_the_right_runs_and_no_results():
    d = X.doe_design({"TPU wt%": (3, 7), "bath T (°C)": (5, 25)}, "2-level full factorial", seed=1)
    assert len(d["runs"]) == 4 and all(r["result"] is None for r in d["runs"])
    lows = sorted({r["TPU wt%"] for r in d["runs"]})
    assert lows == [3, 7]
    ccd = X.doe_design({"a": (0, 1), "b": (0, 1), "c": (0, 1)}, "central composite (face-centred)",
                       center_points=2, randomise=False)
    assert len(ccd["runs"]) == 8 + 6 + 1 + 2
    lhs = X.doe_design({"a": (0, 10), "b": (100, 200)}, "Latin hypercube", runs=10, seed=3)
    a = sorted(r["a"] for r in lhs["runs"])
    assert all(i <= v < i + 1 for i, v in enumerate(a))        # one point per stratum
    assert "no response" in d["note"]
    with pytest.raises(ValueError):
        X.doe_design({"a": (1, 1)})
    with pytest.raises(ValueError, match="too many"):
        X.doe_design({f"f{i}": (0, 1) for i in range(7)}, "3-level full factorial")


# ------------------------------------------------------------------ export verification
def test_excel_and_origin_exports_read_back_identically(tmp_path, analysed):
    from aerolab.core import measurements as M
    from aerolab.io import excel as XL, origin as O

    report = XL.ExcelReport()
    items, runs = [], []
    for mid, result in analysed.items():
        if isinstance(result, list):
            continue
        m = M.get(mid)
        report.add(XL.RunRecord(mid, m, result))
        items.append(O.OriginExportItem(mid, m, result))
        runs.append((mid, m.name, result.metrics))
    path = XL.write_workbook(report, tmp_path / "check.xlsx")
    ex = X.verify_excel_export(path, runs)
    assert ex["ok"], ex["mismatches"][:3]
    assert ex["checked"] > 100
    O.write_script_package(items, tmp_path / "origin")
    og = X.verify_origin_package(tmp_path / "origin", items)
    assert og["ok"], og["mismatches"][:3]
    assert og["checked"] > 1000


def test_verification_catches_a_changed_value(tmp_path, analysed):
    from aerolab.core import measurements as M
    from aerolab.core.curves import Metric
    from aerolab.io import excel as XL

    m = M.get("tga")
    result = analysed["tga"]
    path = XL.write_workbook(XL.ExcelReport(runs=[XL.RunRecord("s", m, result)]), tmp_path / "x.xlsx")
    tampered = [Metric(x.name, (x.value * 1.001 if isinstance(x.value, float) and math.isfinite(x.value) else x.value))
                for x in result.metrics]
    assert not X.verify_excel_export(path, [("s", m.name, tampered)])["ok"]
