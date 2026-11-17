"""Sample-to-experiment workspace: records, lineage, replication, migrations and archives."""
from __future__ import annotations

import json
import math
import zipfile

import pytest

from aerolab.core import workspace as W


def _sample(sid="NFT-4", **kw):
    base = dict(sample_id=sid, name="TPU nanofibre", batch="B1",
                components=[W.Component("TPU", 0.93, 1.11), W.Component("TEPI", 0.07, 1.006)],
                process={"flow rate": {"value": 2.0, "unit": "mL/h"}, "bath": {"text": "ethanol"}},
                bulk_density_g_cm3=0.1508, bulk_density_sigma=0.002,
                geometry={"diameter": {"value": 90.0, "unit": "µm"}},
                thermal_history=[{"step": "supercritical drying", "temperature_c": 40, "duration_min": 240}])
    base.update(kw)
    return W.Sample(**base)


def test_derived_values_carry_their_formula():
    ws = W.Workspace()
    s = ws.add_sample(_sample())
    d = s.derived()
    rho_s = 1.0 / (0.93 / 1.11 + 0.07 / 1.006)
    assert d["skeletal density"]["value"] == pytest.approx(rho_s)
    assert "rule of mixtures" in d["skeletal density"]["source"]
    assert d["porosity"]["value"] == pytest.approx((1 - 0.1508 / rho_s) * 100)
    assert d["porosity"]["sigma"] == pytest.approx(100 * 0.002 / rho_s, rel=1e-3)
    assert "Eq. 1" in d["porosity"]["source"]


@pytest.mark.parametrize("bad,match", [
    (dict(components=[W.Component("TPU", 93.0, 1.11)]), "fractions"),
    (dict(bulk_density_g_cm3=-1.0), "positive"),
    (dict(bulk_density_g_cm3=2.0, skeletal_density_g_cm3=1.1), "negative porosity"),
    (dict(replicate_of="nope"), "unknown"),
    (dict(sample_id="../x"), "sample id"),
])
def test_inconsistent_samples_are_refused(bad, match):
    ws = W.Workspace()
    with pytest.raises(W.WorkspaceError, match=match):
        ws.add_sample(_sample(**bad))


def test_replicates_copy_composition_but_not_measurements():
    ws = W.Workspace()
    ws.add_sample(_sample())
    r1 = ws.add_replicate("NFT-4")
    r2 = ws.add_replicate(r1.sample_id)             # a replicate of a replicate joins the same group
    assert r1.replicate_of == r2.replicate_of == "NFT-4"
    assert r1.components == ws.samples["NFT-4"].components
    assert r1.bulk_density_g_cm3 is None
    assert [s.sample_id for s in ws.replicates(r2.sample_id)] == ["NFT-4", r1.sample_id, r2.sample_id]


def test_replicate_statistics_match_a_hand_calculation():
    st = W.replicate_statistics([3.4, 3.6, 3.5, None, float("nan")])
    assert st["n"] == 3 and st["mean"] == pytest.approx(3.5)
    assert st["sd"] == pytest.approx(0.1)
    # t(0.975, 2) = 4.302653 ; 3.5 ± 4.302653·0.1/√3
    assert st["ci95_high"] == pytest.approx(3.5 + 4.302653 * 0.1 / math.sqrt(3), rel=1e-6)
    single = W.replicate_statistics([2.0])
    assert single["mean"] == 2.0 and math.isnan(single["sd"])


def test_lineage_is_the_chain_of_custody(tmp_path):
    raw = tmp_path / "tensile.csv"
    raw.write_text("Strain (%),Stress (MPa)\n0,0\n1,0.3\n")
    ws = W.Workspace()
    ws.actor = "EY"
    ws.add_sample(_sample())
    ws.add_experiment(W.Experiment("E1", "NFT-4", "stress_strain",
                                   W.Instrument("Instron", "5965", "S123", "2026-10-01")))
    att = ws.attach_file(raw, experiment_id="E1")
    ws.link_run("E1", "tensile::stress_strain")
    history = ws.history("sample:NFT-4")
    actions = [e.action for e in history]
    assert actions == ["sample created", "experiment created", "file attached", "run linked"]
    assert all(e.actor == "EY" for e in history)
    assert att.sha256[:16] in history[2].detail
    assert ws.experiment_for_run("tensile::stress_strain").experiment_id == "E1"


def test_changed_or_missing_attachments_are_detected(tmp_path):
    raw = tmp_path / "a.csv"
    raw.write_text("1,2\n")
    ws = W.Workspace()
    ws.add_sample(_sample())
    att = ws.attach_file(raw, sample_id="NFT-4")
    assert ws.verify_attachments() == [(att, "ok")]
    raw.write_text("1,3\n")
    assert ws.verify_attachments()[0][1] == "changed"
    raw.unlink()
    assert ws.verify_attachments()[0][1] == "missing"
    assert ws.lineage[-1].action == "attachment missing"


def test_images_link_to_a_sample_and_an_experiment(tmp_path):
    img = tmp_path / "fracture.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    ws = W.Workspace()
    ws.add_sample(_sample())
    ws.add_experiment(W.Experiment("E1", "NFT-4", "stress_strain"))
    a = ws.attach_file(img, experiment_id="E1")
    assert a.kind == "image"
    assert ws.images_for(experiment_id="E1") == [a]


def test_bad_calibration_date_is_refused():
    ws = W.Workspace()
    ws.add_sample(_sample())
    with pytest.raises(W.WorkspaceError, match="ISO"):
        ws.add_experiment(W.Experiment("E1", "NFT-4", "tga", W.Instrument(calibration_date="last week")))


def test_removing_a_sample_with_experiments_is_refused():
    ws = W.Workspace()
    ws.add_sample(_sample())
    ws.add_experiment(W.Experiment("E1", "NFT-4", "tga"))
    with pytest.raises(W.WorkspaceError, match="experiments"):
        ws.remove_sample("NFT-4")


def test_round_trip_and_forward_compatible_reading():
    ws = W.Workspace()
    ws.add_sample(_sample())
    ws.add_experiment(W.Experiment("E1", "NFT-4", "tga", W.Instrument("TGA 550", calibration_date="2026-01-05")))
    data = json.loads(json.dumps(ws.to_dict()))
    data["samples"][0]["field_from_the_future"] = 1          # a newer version added a field
    back = W.Workspace.from_dict(data)
    assert back.samples["NFT-4"] == ws.samples["NFT-4"]
    assert back.experiments["E1"].instrument.calibration_date == "2026-01-05"


# ------------------------------------------------------------------ migrations
def test_v1_session_is_migrated_without_losing_runs():
    v1 = {"format": "aerolab-session", "version": 1, "runs": [{"sample": "x", "measurement": "tga"}],
          "manual": []}
    v2, notes = W.migrate(v1)
    assert v2["schema_version"] == 2 and v2["runs"] == v1["runs"]
    assert v2["workspace"]["lineage"][0]["action"] == "migrated"
    assert notes and "schema 1" in notes[0]
    assert v1["version"] == 1, "the input payload must not be modified"
    again, notes2 = W.migrate(v2)
    assert again["schema_version"] == 2 and not notes2


def test_a_newer_schema_is_refused():
    with pytest.raises(W.WorkspaceError, match="newer"):
        W.migrate({"format": "aerolab-session", "schema_version": 99})


# ------------------------------------------------------------------ archives
def _archive(tmp_path):
    raw = tmp_path / "src" / "tga.csv"
    raw.parent.mkdir()
    raw.write_text("T,w\n30,100\n600,40\n")
    ws = W.Workspace()
    ws.add_sample(_sample())
    ws.attach_file(raw, sample_id="NFT-4")
    payload = {"format": "aerolab-session", "schema_version": 2, "runs": [], "manual": [],
               "workspace": ws.to_dict()}
    path, problems = W.export_archive(payload, ws, tmp_path / "out" / "study")
    return path, problems, raw


def test_archive_round_trip_verifies_and_repoints_attachments(tmp_path):
    path, problems, raw = _archive(tmp_path)
    assert path.suffix == ".aerolabz" and not problems
    payload, notes = W.import_archive(path, tmp_path / "unpacked")
    ws = W.Workspace.from_dict(payload["workspace"])
    att = next(iter(ws.attachments.values()))
    assert att.path.startswith(str((tmp_path / "unpacked").resolve()))
    assert W.sha256_file(att.path) == W.sha256_file(raw)
    assert ws.lineage[-1].action == "archive imported"


def test_archive_leaves_out_a_file_changed_since_attaching(tmp_path):
    raw = tmp_path / "a.csv"
    raw.write_text("1\n")
    ws = W.Workspace()
    ws.add_sample(_sample())
    ws.attach_file(raw, sample_id="NFT-4")
    raw.write_text("2\n")
    _path, problems = W.export_archive({"format": "aerolab-session"}, ws, tmp_path / "x.aerolabz")
    assert problems and "changed" in problems[0]


def test_tampered_archive_is_refused(tmp_path):
    path, _p, _raw = _archive(tmp_path)
    tampered = tmp_path / "tampered.aerolabz"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.startswith("attachments/"):
                data = data.replace(b"600", b"700")
            dst.writestr(info, data)
    with pytest.raises(W.WorkspaceError, match="SHA-256"):
        W.import_archive(tampered, tmp_path / "t")


@pytest.mark.parametrize("member", ["../evil.txt", "/abs.txt", "C:/win.txt", "attachments/../../x"])
def test_path_traversal_in_an_archive_is_refused(tmp_path, member):
    bad = tmp_path / "bad.aerolabz"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "aerolab-archive", "files": []}))
        z.writestr("session.json", json.dumps({"format": "aerolab-session"}))
        z.writestr(member, "x")
    with pytest.raises(W.WorkspaceError, match="unsafe"):
        W.import_archive(bad, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_zip_bomb_ratio_is_refused(tmp_path):
    bad = tmp_path / "bomb.aerolabz"
    with zipfile.ZipFile(bad, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({"format": "aerolab-archive", "files": []}))
        z.writestr("session.json", json.dumps({"format": "aerolab-session"}))
        z.writestr("attachments/zeros.bin", b"\0" * (20 * 1024 * 1024))
    with pytest.raises(W.WorkspaceError, match="compression"):
        W.import_archive(bad, tmp_path / "out")


def test_not_a_zip(tmp_path):
    bad = tmp_path / "nope.aerolabz"
    bad.write_text("hello")
    with pytest.raises(W.WorkspaceError):
        W.import_archive(bad, tmp_path / "out")


def test_existing_different_file_is_not_overwritten_on_import(tmp_path):
    path, _p, raw = _archive(tmp_path)
    dest = tmp_path / "unpacked"
    dest.mkdir()
    payload, _ = W.import_archive(path, dest)
    att = next(iter(W.Workspace.from_dict(payload["workspace"]).attachments.values()))
    (dest / __import__("pathlib").Path(att.path).name).write_text("someone else's file")
    payload2, _ = W.import_archive(path, dest)
    att2 = next(iter(W.Workspace.from_dict(payload2["workspace"]).attachments.values()))
    assert att2.path != att.path and W.sha256_file(att2.path) == W.sha256_file(raw)


# ------------------------------------------------------------------ session integration
def test_session_workspace_edits_are_undoable_and_saved(qapp, tmp_path):
    from aerolab.ui.state import Session

    s = Session()
    s.edit_workspace("add sample", lambda ws: ws.add_sample(_sample()))
    assert "NFT-4" in s.workspace.samples
    with pytest.raises(W.WorkspaceError):
        s.edit_workspace("bad", lambda ws: ws.add_sample(_sample()))   # duplicate id
    assert len(s.workspace.samples) == 1                                # failed edit left no trace
    s.undo()
    assert not s.workspace.samples
    s.redo()
    assert "NFT-4" in s.workspace.samples
    s.add_note("Fibre B1 looked glossy before drying.", ("sample:NFT-4",))

    path = s.save_project(tmp_path / "ws.aerolab")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    other = Session()
    other.load_project(path)
    assert other.workspace.samples["NFT-4"].components[0].name == "TPU"
    assert other.notebook[0].links == ("sample:NFT-4",)


def test_session_opens_a_v1_file_and_reports_the_migration(qapp, tmp_path):
    from aerolab.ui.state import Session

    v1 = tmp_path / "old.aerolab"
    v1.write_text(json.dumps({"format": "aerolab-session", "version": 1, "project": "old",
                              "runs": [], "manual": []}), encoding="utf-8")
    s = Session()
    messages = []
    s.status.connect(lambda m, level: messages.append(m))
    s.load_project(v1)
    assert s.last_migration_notes and "Upgraded" in messages[-1]
    assert s.workspace.lineage[0].action == "migrated"


def test_session_archive_round_trip(qapp, tmp_path):
    from aerolab.ui.state import Session

    raw = tmp_path / "raw.csv"
    raw.write_text("1,2\n3,4\n")
    s = Session()
    s.edit_workspace("add", lambda ws: ws.add_sample(_sample()))
    s.edit_workspace("attach", lambda ws: ws.attach_file(raw, sample_id="NFT-4"))
    out, problems = s.save_archive(tmp_path / "study")
    assert not problems
    other = Session()
    _loaded, _notes = other.open_archive(out, tmp_path / "extract")
    att = next(iter(other.workspace.attachments.values()))
    assert W.sha256_file(att.path) == W.sha256_file(raw)


# ------------------------------------------------------------------ the page
def test_workspace_page_end_to_end(qapp, tmp_path):
    from aerolab.ui.pages.workspace import WorkspacePage
    from aerolab.ui.state import Session

    session = Session()
    page = WorkspacePage(session)
    sid = page.new_sample("NFT-4")
    assert sid == "NFT-4" and page.sample_list.count() == 1

    page.f_name.setText("TPU nanofibre")
    page.f_rho_b.setText("0,1508")                     # a decimal comma is accepted
    page.t_components.setRowCount(2)
    for r, row in enumerate((["TPU", "0.93", "1.11"], ["TEPI", "0.07", "1.006"])):
        for c, v in enumerate(row):
            page.t_components.setItem(r, c, __import__("PySide6.QtWidgets", fromlist=["x"]).QTableWidgetItem(v))
    assert page.apply_changes(), page.form_error.text()
    s = session.workspace.samples["NFT-4"]
    assert s.bulk_density_g_cm3 == pytest.approx(0.1508)
    assert "porosity" in page.derived.text()

    page.t_components.item(0, 1).setText("93")       # a percentage instead of a fraction
    assert not page.apply_changes()
    assert "fractions" in page.form_error.text()
    assert session.workspace.samples["NFT-4"].components[0].mass_fraction == pytest.approx(0.93)

    page.e_instrument.setText("Instron")
    page.e_cal.setText("2026-10-01")
    eid = page.add_experiment()
    assert eid == "E1" and page.exp_table.rowCount() == 1

    raw = tmp_path / "pull.csv"
    raw.write_text("Strain (%),Stress (MPa)\n0,0\n")
    assert page.attach_files([str(raw)]) == 1
    assert page.att_table.rowCount() == 1
    assert page.verify_files() and list(page._status.values()) == ["ok"]

    rep = page.add_replicate()
    assert rep and session.workspace.samples[rep].replicate_of == "NFT-4"
    actions = [page.lineage.item(i).text() for i in range(page.lineage.count())]
    assert actions                                      # the replicate's own creation is logged

    out = page.save_archive(str(tmp_path / "study"))
    assert out and out[0].exists()
    session.undo()                                      # workspace edits are undoable
    page.deleteLater()
