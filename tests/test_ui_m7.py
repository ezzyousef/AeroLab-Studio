"""UI milestone: notebook, layout templates, streaming preview, navigation, high DPI."""
from __future__ import annotations

import numpy as np
import pytest


def test_notebook_entries_are_linked_undoable_and_exported(qapp, tmp_path):
    from aerolab.core import workspace as W
    from aerolab.ui.pages.notebook import NotebookPage
    from aerolab.ui.state import Session

    s = Session()
    s.edit_workspace("sample", lambda ws: ws.add_sample(W.Sample("NFT-4")))
    page = NotebookPage(s)
    page.editor.setPlainText("Gel looked cloudy <b>before</b> drying.")
    page.link_combo.setCurrentIndex(page.link_combo.findData("sample:NFT-4"))
    entry = page.add_entry()
    assert entry.links == ("sample:NFT-4",) and page.entries.count() == 1
    assert page.add_entry() is None                     # empty text is not an entry
    out = page.export_markdown(str(tmp_path / "nb.md"))
    assert "<b>before</b>" in (tmp_path / "nb.md").read_text(encoding="utf-8")   # kept as plain text
    s.undo()
    assert page.entries.count() == 0
    page.deleteLater()


def test_streaming_preview_does_not_build_every_row(qapp):
    from aerolab.io.readers import Dataset
    from aerolab.ui.widgets import DatasetModel

    n = 300_000
    ds = Dataset("big", ["t", "y"], [np.arange(n, dtype=float), np.sin(np.arange(n) / 100.0)])
    model = DatasetModel(ds)
    assert model.rowCount() == DatasetModel.CHUNK and model.canFetchMore()
    model.fetchMore()
    assert model.rowCount() == 2 * DatasetModel.CHUNK
    assert model.data(model.index(5, 0)) == "5"
    assert model.headerData(1, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Horizontal) == "y"


def test_data_page_overview_lists_every_file_and_its_warnings(qapp, tmp_path):
    from aerolab.ui.pages.data import DataPage
    from aerolab.ui.state import Session

    # A short row is kept and warned about; a wide row refuses the file (Codex finding 2).
    short = tmp_path / "short.csv"
    short.write_text("Strain (%),Stress (MPa),Time (s)\n0,0,0\n1,0.3\n2,0.6,2\n3,0.8,3\n")
    wide = tmp_path / "wide.csv"
    wide.write_text("Strain (%),Stress (MPa)\n0,0\n1,0.3,9\n2,0.6\n3,0.8\n")
    s = Session()
    errors = []
    s.status.connect(lambda m, level: errors.append(m) if level in ("error", "warning") else None)
    page = DataPage(s)
    page.load_samples()
    page.import_paths([str(short), str(wide)])
    qapp.processEvents()
    assert page.overview.rowCount() == len(s.datasets)
    assert not any(d.name == "wide" for d in s.datasets)
    assert any("line 3 has 3 values" in m for m in errors)
    row = next(r for r in range(page.overview.rowCount()) if page.overview.item(r, 0).text() == "short")
    assert "fewer than 3 values" in page.overview.item(row, 4).text()
    page.deleteLater()


def test_plots_page_layout_templates(qapp, samples_dir):
    from aerolab.core import measurements as M
    from aerolab.io import readers as R
    from aerolab.ui.pages.plots import PlotsPage
    from aerolab.ui.state import Session

    s = Session()
    m = M.get("stress_strain")
    ds = R.read_any(samples_dir / m.sample)[0]
    mapping = m.match_columns(ds.headers)
    for name in ("A", "B", "C"):
        s.add_run(name, m, m.run({k: ds.columns[v] for k, v in mapping.items() if v is not None}))
    page = PlotsPage(s)
    page.refresh()
    page.layout_combo.setCurrentText("Grid (2 × 2)")
    assert page.last_panels == 3
    visible = [ax for ax in page.canvas.figure.axes if ax.axison]
    assert len(visible) == 3
    page.deleteLater()


def test_navigation_is_grouped_by_task_and_scrolls(qapp):
    from aerolab.ui import app as A

    groups = list(dict.fromkeys(g for _k, _c, g in A.PAGES))
    assert groups == ["Session", "Analyse", "Studios", "Output"]
    w = A.MainWindow()
    assert w.findChild(__import__("PySide6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea, "NavRailScroll")
    for key in ("workspace", "notebook", "mechanics", "materials", "explorer"):
        w.go_to(key)
        assert w.stack.currentWidget() is w.pages[key]
    w.close()


def test_high_dpi_policy_is_pass_through_when_set_before_the_app():
    """Run in a fresh interpreter: the policy only takes effect before QApplication exists."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    code = "; ".join([
        "from aerolab.ui.app import configure_high_dpi", "configure_high_dpi()",
        "from PySide6.QtWidgets import QApplication", "from PySide6.QtCore import Qt",
        "app = QApplication([])",
        "print(QApplication.highDpiScaleFactorRoundingPolicy() == Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)"])
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                         cwd=str(Path(__file__).resolve().parents[1]), timeout=120)
    assert out.stdout.strip().endswith("True"), out.stderr[-500:]
