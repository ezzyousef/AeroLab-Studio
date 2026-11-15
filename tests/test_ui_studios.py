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
