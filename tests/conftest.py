"""Shared fixtures. Qt runs offscreen so the suite works over SSH and in CI."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")

SAMPLES = ROOT / "aerolab" / "resources" / "samples"


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    assert SAMPLES.is_dir(), f"demo datasets are missing from {SAMPLES}"
    return SAMPLES


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session — Qt allows only one."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def analysed(samples_dir):
    """Every demo dataset, imported and analysed. Returns {measurement id: AnalysisResult}."""
    from aerolab.core import measurements as M
    from aerolab.io import readers as R

    out = {}
    for measurement in M.MEASUREMENTS:
        dataset = R.read_any(samples_dir / measurement.sample)[0]
        mapping = measurement.match_columns(dataset.headers)
        columns = {k: dataset.columns[v] for k, v in mapping.items() if v is not None}
        if measurement.kind == "table":
            rows = [{k: float(dataset.columns[v][i]) for k, v in mapping.items()
                     if v is not None} for i in range(dataset.n_rows)]
            out[measurement.id] = measurement.run_table(rows)
        else:
            out[measurement.id] = measurement.run(columns)
    return out
