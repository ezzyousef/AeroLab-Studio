"""Regression tests for the independent Codex review of upgrade 06 (bda8754).

Report: AI_Engineering_Knowledge_Base/reports/codex/06-aerolab-upgrade-review.md.
Each test is built from the reviewer's concrete input and failed on bda8754.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile

import numpy as np
import pytest

from aerolab.core import curves as C, equations as E, uncertainty as U, workspace as W
from aerolab.io import readers as R


# --------------------------------------------------------------------- finding 1 (high)
def _archive_with(tmp_path, name: str, content: bytes):
    src = tmp_path / "src" / name
    src.parent.mkdir()
    src.write_bytes(content)
    ws = W.Workspace()
    ws.add_sample(W.Sample("S1"))
    ws.attach_file(src, sample_id="S1")
    path, _ = W.export_archive({"format": "aerolab-session", "schema_version": 2, "workspace": ws.to_dict()},
                               ws, tmp_path / "a.aerolabz")
    return path, hashlib.sha256(content).hexdigest()


def test_codex1_collision_fallback_is_hash_checked(tmp_path):
    """x.txt and x_<digest8>.txt both exist with OTHER content: neither may be accepted."""
    path, digest = _archive_with(tmp_path, "x.txt", b"the real attachment")
    base = f"{digest[:12]}_x"                       # the attachment's name inside the archive
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / f"{base}.txt").write_bytes(b"someone else's file")
    (dest / f"{base}_{digest[:8]}.txt").write_bytes(b"planted, different content")
    payload, _ = W.import_archive(path, dest)
    att = next(iter(W.Workspace.from_dict(payload["workspace"]).attachments.values()))
    assert W.sha256_file(att.path) == digest
    assert (dest / f"{base}.txt").read_bytes() == b"someone else's file"            # untouched
    assert (dest / f"{base}_{digest[:8]}.txt").read_bytes() == b"planted, different content"


def test_codex1_a_link_candidate_is_skipped_and_never_written_through(tmp_path, monkeypatch):
    """A (dangling) symlink at a candidate name must be skipped, not followed. Windows here
    cannot create symlinks without privilege, so the link test is made by marking the
    candidate path as a link; the code under test only asks os.path.islink."""
    path, digest = _archive_with(tmp_path, "x.txt", b"payload")
    base = f"{digest[:12]}_x"
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / f"{base}.txt").write_bytes(b"other")
    planted = dest / f"{base}_{digest[:8]}.txt"
    real_islink = os.path.islink
    monkeypatch.setattr(W.os.path, "islink", lambda p: os.fspath(p) == os.fspath(planted) or real_islink(p))
    payload, _ = W.import_archive(path, dest)
    att = next(iter(W.Workspace.from_dict(payload["workspace"]).attachments.values()))
    assert os.fspath(att.path) != os.fspath(planted)
    assert not planted.exists()
    assert W.sha256_file(att.path) == digest


def test_codex1_new_files_are_created_exclusively(tmp_path, monkeypatch):
    """If a file appears between the check and the write, it is not overwritten."""
    target_dir = tmp_path / "d"
    target_dir.mkdir()
    data = b"abc"
    digest = hashlib.sha256(data).hexdigest()
    real_lexists = os.path.lexists
    raced = target_dir / "f.bin"

    def lexists(p):
        if os.fspath(p) == os.fspath(raced) and not raced.exists():
            raced.write_bytes(b"racer")            # appears right after the existence check
            return False
        return real_lexists(p)
    monkeypatch.setattr(W.os.path, "lexists", lexists)
    out = W._place_attachment(target_dir.resolve(), "f.bin", data, digest)
    assert raced.read_bytes() == b"racer" and out.read_bytes() == data


# --------------------------------------------------------------------- finding 2 (high)
def test_codex2_headerless_first_row_wider_is_refused(tmp_path):
    p = tmp_path / "headerless.csv"
    p.write_text("0,99,100\n1,2\n2,4\n3,6\n")
    with pytest.raises(R.ImportError_, match="line 1 has 3 values"):
        R.read_any(p)


def test_codex2_wide_middle_row_cannot_reach_the_analysis(tmp_path):
    p = tmp_path / "middle.csv"
    p.write_text("Strain (%),Stress (MPa)\n0,0\n1,0.3\n2,0.6,0.9\n3,0.8\n4,0.9\n")
    with pytest.raises(R.ImportError_, match="line 4 has 3 values but the header has 2"):
        R.read_any(p)


def test_codex2_trailing_empty_fields_are_still_accepted(tmp_path):
    p = tmp_path / "trailing.csv"
    p.write_text("a,b\n1,2,\n3,4,,\n5,6\n")
    ds = R.read_any(p)[0]
    np.testing.assert_allclose(ds.column("b"), [2, 4, 6])


def test_codex2_excel_rows_wider_than_the_header_are_refused(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in (["Strain (%)", "Stress (MPa)"], [0, 0], [1, 0.3, 77], [2, 0.6], [3, 0.8]):
        ws.append(row)
    p = tmp_path / "wide.xlsx"
    wb.save(p)
    with pytest.raises(R.ImportError_, match="line 3 has 3 values"):
        R.read_any(p)


# --------------------------------------------------------------------- finding 3 (high)
def test_codex3_npz_expansion_budget(tmp_path, monkeypatch):
    p = tmp_path / "zeros.npz"
    np.savez_compressed(p, a=np.zeros(2_000_000))            # 16 MB expanded, tiny on disk
    assert p.stat().st_size < 1_000_000
    monkeypatch.setattr(R, "MAX_UNCOMPRESSED_BYTES", 4 * 1024 * 1024)
    with pytest.raises(R.ImportError_, match="expands to"):
        R.read_any(p)


def test_codex3_npz_value_budget_reads_headers_only(tmp_path, monkeypatch):
    p = tmp_path / "many.npz"
    np.savez_compressed(p, a=np.zeros(300_000), b=np.zeros(300_000))
    monkeypatch.setattr(R, "MAX_VALUES", 500_000)
    with pytest.raises(R.ImportError_, match="values in total"):
        R.read_any(p)


def test_codex3_xlsx_cell_budget(tmp_path, monkeypatch):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["x", "y"])
    for i in range(2000):
        ws.append([i, 2 * i])
    p = tmp_path / "big.xlsx"
    wb.save(p)
    monkeypatch.setattr(R, "MAX_VALUES", 1000)
    with pytest.raises(R.ImportError_, match="cells"):
        R.read_any(p)


def test_codex3_xlsx_expansion_budget(tmp_path, monkeypatch):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["x", "y"])
    wb.active.append([1, 2])
    p = tmp_path / "small.xlsx"
    wb.save(p)
    monkeypatch.setattr(R, "MAX_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(R.ImportError_, match="expands to"):
        R.read_any(p)


# --------------------------------------------------------------------- finding 4 (medium)
def test_codex4_negative_bulk_density_draws_are_rejected():
    eq = E.get("relative_density")
    mc = U.monte_carlo(eq, {"rho_b": 0.15, "rho_s": 1.0}, {"rho_b": 0.3}, n=20000, seed=2)
    # P(ρb < 0) = Φ(−0.5) = 0.3085 for ρb ~ N(0.15, 0.3)
    assert mc.rejected_fraction == pytest.approx(0.3085, abs=0.015)
    assert mc.samples.min() >= 0.0


def test_codex4_relations_between_inputs_are_enforced():
    eq = E.get("porosity_from_density")
    mc = U.monte_carlo(eq, {"rho_b": 0.9, "rho_s": 1.0}, {"rho_b": 0.1}, n=20000, seed=3)
    assert mc.samples.min() >= 0.0                         # no negative porosity (ρb > ρs) kept
    with pytest.raises(ValueError, match="bulk density"):
        U.propagate_linear(eq, {"rho_b": 1.2, "rho_s": 1.0}, {"rho_b": 0.01})
    with pytest.raises(ValueError, match="physical bounds"):
        U.monte_carlo(E.get("relative_density"), {"rho_b": -0.1, "rho_s": 1.0}, {"rho_b": 0.01}, n=200)


# --------------------------------------------------------------------- finding 5 (medium)
def _mc(sd):
    return U.MonteCarloResult(1.0, sd, 1.0, 1.0 - 2 * sd, 1.0 + 2 * sd, 1000, 1000, 0)


def test_codex5_zero_or_nan_linear_sigma_is_not_agreement():
    for sigma, status in ((0.0, "disagree"), (float("nan"), "unavailable")):
        verdict = U.compare(U.LinearResult(1.0, sigma, {}, {}, False), _mc(1.0))
        assert verdict["agree"] is False and verdict["status"] == status
        assert "Monte Carlo 95 %" in verdict["message"]
    exact = U.compare(U.LinearResult(1.0, 0.0, {}, {}, False), _mc(0.0))
    assert exact["agree"] is True and exact["status"] == "exact"


# --------------------------------------------------------------------- finding 6 (medium)
def test_codex6_descending_only_bet_needs_an_explicit_branch():
    x = np.array([0.30, 0.25, 0.20, 0.15, 0.10, 0.05])
    v = 80 * 150 * x / ((1 - x) * (1 - x + 150 * x))
    with pytest.raises(ValueError, match="Choose the branch"):
        C.analyze_sorption_bet(x, v)
    r = C.analyze_sorption_bet(x, v, branch="desorption")
    assert r.meta["branch"] == "desorption"
    assert "declared the desorption branch" in r.metrics[0].note


def test_codex6_branch_choice_is_saved_with_the_run(qapp, tmp_path):
    from aerolab.core import measurements as M
    from aerolab.ui.state import Session

    x = np.array([0.30, 0.25, 0.20, 0.15, 0.10, 0.05])
    v = 80 * 150 * x / ((1 - x) * (1 - x + 150 * x))
    m = M.get("sorption")
    r = m.run({"p_p0": x, "volume_stp": v}, branch="adsorption")
    s = Session()
    s.add_run("iso", m, r, options={"branch": "adsorption"})
    path = s.save_project(tmp_path / "b.aerolab")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["runs"][0]["options"]["branch"] == "adsorption"


# --------------------------------------------------------------------- finding 7 (medium)
def test_codex7_two_analyses_of_one_file_have_distinct_persistent_ids(qapp, tmp_path, samples_dir):
    from aerolab.core import measurements as M
    from aerolab.io import readers as R2
    from aerolab.ui.state import Session

    m = M.get("stress_strain")
    ds = R2.read_any(samples_dir / m.sample)[0]
    cols = {k: ds.columns[v] for k, v in m.match_columns(ds.headers).items() if v is not None}
    s = Session()
    a = s.add_run(ds.name, m, m.run(cols), dataset_name=ds.name)
    b = s.add_run(ds.name, m, m.run(cols, modulus_range=(0.0, 2.0)), dataset_name=ds.name,
                  options={"modulus_range": (0.0, 2.0)})
    assert a.key != b.key

    def link(ws):
        ws.add_sample(W.Sample("S1"))
        ws.add_experiment(W.Experiment("E1", "S1", "stress_strain"))
        ws.add_experiment(W.Experiment("E2", "S1", "stress_strain"))
        ws.link_run("E1", a.key)
        ws.link_run("E2", b.key)
    s.edit_workspace("link", link)
    path = s.save_project(tmp_path / "r.aerolab")
    t = Session()
    t.load_project(path)
    ra, rb = t.runs
    assert (ra.key, rb.key) == (a.key, b.key)                    # persisted, not regenerated
    assert t.workspace.experiment_for_run(ra.key).experiment_id == "E1"
    assert t.workspace.experiment_for_run(rb.key).experiment_id == "E2"


def test_codex7_legacy_links_move_to_the_new_id_only_when_unambiguous(qapp, tmp_path):
    from aerolab.ui.state import Session

    payload = {"format": "aerolab-session", "schema_version": 2, "runs": [
        {"sample": "a", "measurement": "tga", "dataset": "a", "metrics": [], "curves": {}},
        {"sample": "b", "measurement": "tga", "dataset": "b", "metrics": [], "curves": {}},
        {"sample": "b", "measurement": "tga", "dataset": "b", "metrics": [], "curves": {}}],
        "workspace": {"samples": [{"sample_id": "S1"}], "experiments": [
            {"experiment_id": "E1", "sample_id": "S1", "measurement_id": "tga", "run_keys": ["a::tga"]},
            {"experiment_id": "E2", "sample_id": "S1", "measurement_id": "tga", "run_keys": ["b::tga"]}]}}
    p = tmp_path / "legacy.aerolab"
    p.write_text(json.dumps(payload), encoding="utf-8")
    s = Session()
    s.load_project(p)
    assert s.workspace.experiments["E1"].run_keys == [s.runs[0].uid]
    assert s.workspace.experiments["E2"].run_keys == ["b::tga"]           # ambiguous: not guessed
    assert any(e.action == "ambiguous run link kept" for e in s.workspace.lineage)
