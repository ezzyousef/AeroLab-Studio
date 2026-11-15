"""The studio pages, driven headlessly on the demo datasets."""
from __future__ import annotations

import pytest


def _session_with(measurement_ids, samples_dir, options=None):
    from aerolab.core import measurements as M
    from aerolab.io import readers as R
    from aerolab.ui.state import Session

    session = Session()
    for mid in measurement_ids:
        m = M.get(mid)
        ds = R.read_any(samples_dir / m.sample)[0]
        mapping = m.match_columns(ds.headers)
        result = m.run({k: ds.columns[v] for k, v in mapping.items() if v is not None},
                       **(options or {}).get(mid, {}))
        session.add_run(ds.name, m, result, dataset_name=ds.name, source=str(samples_dir / m.sample),
                        mapping=mapping)
    return session


def test_mechanics_studio_handles_every_mechanical_kind(qapp, samples_dir):
    from aerolab.ui.pages.mechanics import MECHANICAL_KINDS, MechanicsPage

    session = _session_with(MECHANICAL_KINDS, samples_dir,
                            {"stress_relaxation": {"strain_pct": 5.0}, "creep": {"stress_mpa": 0.5}})
    page = MechanicsPage(session)
    page.refresh()
    assert page.run_combo.count() == len(MECHANICAL_KINDS)
    seen = set()
    for run in session.runs:
        page.select_run(run.run_id)
        assert page.last, f"{run.measurement.id}: {page.summary.text()}"
        assert page.table.rowCount() > 0
        seen.add(page.last["kind"])
    assert seen == {"sensitivity", "cycles", "sn", "strain_life", "visco"}
    page.deleteLater()


def test_mechanics_studio_shows_images_linked_through_the_workspace(qapp, samples_dir, tmp_path):
    from PySide6.QtGui import QColor, QPixmap
    from aerolab.core import workspace as W
    from aerolab.ui.pages.mechanics import MechanicsPage

    session = _session_with(["stress_strain"], samples_dir)
    run = session.runs[0]
    img = tmp_path / "fracture.png"
    pix = QPixmap(40, 30)
    pix.fill(QColor("#336699"))
    assert pix.save(str(img))

    def change(ws):
        ws.add_sample(W.Sample("NFT-4"))
        ws.add_experiment(W.Experiment("E1", "NFT-4", "stress_strain"))
        ws.link_run("E1", run.key)
        ws.attach_file(img, experiment_id="E1")
    session.edit_workspace("link", change)
    page = MechanicsPage(session)
    page.refresh()
    assert page.image_list.count() == 1
    assert page.image_view.pixmap() is not None and not page.image_view.pixmap().isNull()
    page.deleteLater()


def test_mechanics_studio_recomputes_after_a_session_round_trip(qapp, samples_dir, tmp_path):
    from aerolab.ui.pages.mechanics import MechanicsPage
    from aerolab.ui.state import Session

    session = _session_with(["cyclic_tension", "creep"], samples_dir, {"creep": {"stress_mpa": 0.5}})
    path = session.save_project(tmp_path / "m.aerolab")
    reopened = Session()
    reopened.load_project(path)
    page = MechanicsPage(reopened)
    page.refresh()
    kinds = set()
    for run in reopened.runs:
        page.select_run(run.run_id)
        kinds.add(page.last.get("kind"))
    assert kinds == {"cycles", "visco"}
    page.deleteLater()


def test_materials_studio_views_and_qc(qapp, samples_dir):
    from aerolab.core import workspace as W
    from aerolab.ui.pages.materials import MaterialsPage

    kinds = ("tga", "dsc", "sorption", "crossover", "k_density", "herschel_bulkley")
    session = _session_with(kinds, samples_dir)
    session.edit_workspace("sample", lambda ws: ws.add_sample(W.Sample(
        "T100-S100", bulk_density_g_cm3=0.211, skeletal_density_g_cm3=1.058)))
    page = MaterialsPage(session)
    page.refresh()
    seen = {}
    for run in session.runs:
        page.select_run(run.run_id)
        seen[run.measurement.id] = page.last.get("kind")
        assert page.flags.count() >= 1
        assert any("Not linked" in m for _l, m in page.last["flags"])
    assert seen == {"tga": "tga", "dsc": "dsc", "sorption": "porosity", "crossover": "lver",
                    "k_density": "k_density", "herschel_bulkley": "generic"}

    # porosity summary picks up the sample's densities
    page.select_run(next(r.run_id for r in session.runs if r.measurement.id == "sorption"))
    page.sample_combo.setCurrentIndex(page.sample_combo.findData("T100-S100"))
    assert "Pore volume seen by N₂" in page.last["summary"]

    # crystallinity only with a user-supplied ΔH°m
    page.select_run(next(r.run_id for r in session.runs if r.measurement.id == "dsc"))
    page.dh100.setText("196.8")
    page.polymer_fraction.setText("0.67")
    page._show()
    endo = [r for r in page.last["rows"] if r["kind"] == "endotherm"]
    assert endo and endo[0]["crystallinity"] > 0
    page.deleteLater()


def test_explorer_compare_surface_doe_report(qapp, samples_dir, tmp_path):
    import numpy as np
    from PySide6.QtWidgets import QTableWidgetItem
    from aerolab.core import measurements as M, workspace as W
    from aerolab.core.curves import AnalysisResult, Metric
    from aerolab.ui.pages.explorer import ExplorerPage
    from aerolab.ui.state import Session

    session = Session()
    m = M.get("thermal_point")

    def change(ws):
        for i, (c, t) in enumerate((c, t) for c in (3.0, 5.0, 7.0) for t in (5.0, 15.0, 25.0)):
            ws.add_sample(W.Sample(f"S{i}", batch=f"C{c:g}", bulk_density_g_cm3=0.1 + 0.01 * i,
                                   process={"TPU": {"value": c, "unit": "wt%"}, "bath": {"value": t, "unit": "°C"}}))
    session.edit_workspace("samples", change)
    for i, (c, t) in enumerate((c, t) for c in (3.0, 5.0, 7.0) for t in (5.0, 15.0, 25.0)):
        y = 20 + 0.8 * (c - 5.2) ** 2 + 0.01 * (t - 14) ** 2
        session.add_run(f"S{i}", m, AnalysisResult("thermal_point", [Metric("k", y, "mW/(m·K)")], {}, {}))
    page = ExplorerPage(session)
    page.refresh()
    page.metric_combo.setCurrentIndex(page.metric_combo.findData("k"))
    page.ref_combo.setCurrentIndex(page.ref_combo.findData("S0"))
    assert page.last["kind"] == "compare" and set(page.last["groups"]) == {"C3", "C5", "C7"}
    assert page.values_table.rowCount() == 9

    page.f1.setCurrentIndex(page.f1.findData("TPU"))
    page.f2.setCurrentIndex(page.f2.findData("bath"))
    page.rs_metric.setCurrentIndex(page.rs_metric.findData("k"))
    rs = page.fit_surface()
    assert rs and rs["stationary"][0] == np.float64(rs["stationary"][0])
    assert abs(rs["stationary"][0] - 5.2) < 1e-6 and rs["stationary_inside"]

    page.eq_combo.setCurrentIndex(page.eq_combo.findData("capillary_number"))
    assert page.last["dimensions"]["n_groups"] == 2

    for r, row in enumerate((["TPU wt%", "3", "7"], ["bath T", "5", "25"])):
        for c, v in enumerate(row):
            page.factors.setItem(r, c, QTableWidgetItem(v))
    d = page.make_design()
    assert d and len(d["runs"]) == 4
    assert page.save_design(str(tmp_path / "doe.csv"))
    assert "result" in (tmp_path / "doe.csv").read_text(encoding="utf-8").splitlines()[0]

    session.edit_workspace("evil name", lambda ws: ws.update_sample("S0", name="<script>alert(1)</script>"))
    html_path, md_path = page.write_report(str(tmp_path / "rep.html"))
    text = html_path.read_text(encoding="utf-8")
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "Equation-library validation" in text and md_path.exists()
    page.deleteLater()
