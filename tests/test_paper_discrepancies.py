"""The two documented disagreements with the source papers, pinned down explicitly.

The app reports its own recomputation and keeps the printed number beside it; neither
result may be "fixed" to match the paper without new evidence. These tests also check
that every published metric carries a unit and a traceable source.
"""
from __future__ import annotations

import math

import pytest

from aerolab.core import equations as E, measurements as M, validation as V


def _case(name_part):
    return next(c for c in V.CASES if name_part in c.name)


def test_effusivity_of_nft4_disagrees_with_the_printed_figure():
    case = _case("Effusivity of NFT-4")
    assert case.expect_match is False and case.basis == "ours"
    assert case.paper_value == pytest.approx(38.2)
    # e = k/sqrt(alpha) = 0.0277 W/(m K) / sqrt(0.196e-6 m^2/s), worked independently
    ours = 0.0277 / math.sqrt(0.196e-6)
    assert ours == pytest.approx(62.57, rel=1e-3)
    assert float(E.get(case.equation).compute(**case.inputs)) == pytest.approx(ours, rel=1e-9)
    # the gap is far beyond rounding: 38.2 would need alpha ≈ 0.53 mm²/s or k ≈ 16.9 mW/(m K)
    assert abs(ours - case.paper_value) / case.paper_value > 0.5
    implied_alpha = (0.0277 / case.paper_value) ** 2 * 1e6
    assert implied_alpha == pytest.approx(0.526, rel=1e-2)


def test_draw_ratio_of_the_final_spinning_step_is_below_one():
    case = _case("Draw ratio")
    assert case.expect_match is False and case.basis == "ours"
    v_exit = (2e-6 / 3600.0) / (math.pi * (159e-6) ** 2 / 4.0) * 60.0     # m/min
    assert v_exit == pytest.approx(1.679, rel=1e-3)
    dr = float(E.get(case.equation).compute(**case.inputs))
    assert dr == pytest.approx(1.0 / v_exit, rel=1e-9)
    assert dr < 1.0, "take-up below the exit speed: no draw-down"


def test_discrepancies_are_reported_as_ok_and_counted():
    results = {r.case.name: r for r in V.run_all()}
    for case in V.CASES:
        if not case.expect_match:
            assert results[case.name].ok, case.name
            assert case.comment
    assert V.summary()["documented_discrepancies"] == 2


def test_every_validation_case_states_its_source_and_basis():
    for case in V.CASES:
        assert case.source, case.name
        assert case.basis in V.BASIS_LABELS, case.name
        assert case.equation in E.REGISTRY, case.name


def test_every_equation_has_a_reference_and_units():
    for eq in E.REGISTRY.values():
        assert eq.reference, eq.id
        for var in (*eq.inputs, eq.output):
            assert var.unit, f"{eq.id}/{var.symbol} has no unit (use '-' for a pure number)"


def test_every_demo_metric_has_a_unit_and_every_measurement_a_reference(analysed):
    for mid, result in analysed.items():
        assert M.get(mid).reference, mid
        results = result if isinstance(result, list) else [result]
        for r in results:
            for metric in r.metrics:
                assert metric.unit, f"{mid}: {metric.name} has no unit"
