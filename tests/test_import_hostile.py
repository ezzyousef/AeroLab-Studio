"""Hostile and malformed files for every importer.

The rule (from the supercap_suite review): validate delimited text at the record level,
and when a row does not fit the header, say so instead of silently dropping or shifting
values. Every failure must be an `ImportError_` with a readable message, never a crash
or a hang.
"""
from __future__ import annotations

import json
import zipfile

import numpy as np
import pytest

from aerolab.core import measurements as M
from aerolab.io import readers as R


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
    return p


# ------------------------------------------------------------------ record-level shape
def test_a_row_wider_than_the_header_is_reported(tmp_path):
    p = _write(tmp_path, "wide_row.csv", "a,b\n1,2\n3,4,5\n6,7\n8,9\n")
    ds = R.read_any(p)[0]
    assert ds.headers == ["a", "b"]
    np.testing.assert_allclose(ds.column("a"), [1, 3, 6, 8])
    warnings = ds.meta.get("warnings", [])
    assert any("3 fields" in w and "row" in w for w in warnings), warnings


def test_every_row_wider_than_the_header_keeps_all_columns(tmp_path):
    p = _write(tmp_path, "all_wide.csv", "a,b\n1,2,3\n4,5,6\n7,8,9\n")
    ds = R.read_any(p)[0]
    assert ds.n_cols == 3
    assert ds.headers[:2] == ["a", "b"]
    np.testing.assert_allclose(ds.columns[2], [3, 6, 9])
    assert any("header" in w for w in ds.meta.get("warnings", []))


def test_a_title_line_above_a_wider_header(tmp_path):
    p = _write(tmp_path, "title.csv",
               "Tensile test of NFT-4\nTime (s),Strain (%),Stress (MPa)\n0,0,0\n1,1,0.2\n2,2,0.4\n3,3,0.5\n")
    ds = R.read_any(p)[0]
    assert ds.headers == ["Time", "Strain", "Stress"]
    assert ds.units == ["s", "%", "MPa"]
    assert ds.n_rows == 4


def test_empty_trailing_fields_do_not_create_a_phantom_column(tmp_path):
    p = _write(tmp_path, "trailing.csv", "T (°C),w (%),\n30,100,\n40,99.5,\n50,99.1,\n")
    ds = R.read_any(p)[0]
    assert ds.headers == ["T", "w"]
    np.testing.assert_allclose(ds.column("w"), [100, 99.5, 99.1])


def test_decimal_comma_with_semicolons(tmp_path):
    p = _write(tmp_path, "eu.csv", "T;w\n30,5;100,0\n40,5;99,5\n50,5;99,1\n")
    ds = R.read_any(p)[0]
    np.testing.assert_allclose(ds.column("T"), [30.5, 40.5, 50.5])
    assert ds.meta["decimal"] == ","


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32"])
def test_utf16_and_utf32_with_bom(tmp_path, encoding):
    text = "Temperature (°C)\tWeight (%)\n30\t100\n40\t99.5\n50\t99.1\n"
    raw = text.encode(encoding)
    if encoding in ("utf-16-le", "utf-16-be"):       # these codecs write no BOM themselves
        raw = ("﻿" + text).encode(encoding)
    p = _write(tmp_path, f"bom_{encoding}.txt", raw)
    ds = R.read_any(p)[0]
    assert ds.headers == ["Temperature", "Weight"]
    assert ds.units == ["°C", "%"]
    np.testing.assert_allclose(ds.column("Weight"), [100, 99.5, 99.1])


def test_nan_rows_survive_import_and_are_dropped_by_the_analyser(tmp_path):
    p = _write(tmp_path, "nan_rows.csv",
               "Strain (%),Stress (MPa)\n0,0\nNaN,NaN\n1,0.3\n,\n2,0.6\n3,0.9\n4,1.1\n5,1.2\n6,1.25\n")
    ds = R.read_any(p)[0]
    assert np.isnan(ds.column("Strain")).sum() >= 1
    m = M.get("stress_strain")
    result = m.run({"strain_pct": ds.column("Strain"), "stress_mpa": ds.column("Stress")}, offset_yield=0)
    assert result.value("Ultimate tensile strength") == pytest.approx(1.25)


def test_quoted_thousands_separator(tmp_path):
    p = _write(tmp_path, "quoted.csv", 'Cycles,Amplitude (MPa)\n"1,000",5.1\n"10,000",4.4\n"100,000",3.9\n')
    ds = R.read_any(p)[0]
    np.testing.assert_allclose(ds.column("Cycles"), [1000, 10000, 100000])


def test_classic_mac_line_endings(tmp_path):
    p = _write(tmp_path, "cr.csv", "a,b\r1,2\r3,4\r5,6\r")
    ds = R.read_any(p)[0]
    np.testing.assert_allclose(ds.column("b"), [2, 4, 6])


# ------------------------------------------------------------------ garbage
def test_binary_garbage_is_refused_cleanly(tmp_path):
    rng = np.random.default_rng(1)
    p = _write(tmp_path, "garbage.csv", bytes(rng.integers(0, 256, 4096, dtype=np.uint8)))
    with pytest.raises(R.ImportError_):
        R.read_any(p)


def test_header_only_file(tmp_path):
    p = _write(tmp_path, "header_only.csv", "Strain (%),Stress (MPa)\n")
    with pytest.raises(R.ImportError_):
        R.read_any(p)


def test_text_only_file(tmp_path):
    p = _write(tmp_path, "prose.txt", "This is a lab note.\nIt has no numbers at all.\nNone.\n")
    with pytest.raises(R.ImportError_):
        R.read_any(p)


def test_oversized_file_is_refused_before_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "MAX_FILE_BYTES", 1000)
    p = _write(tmp_path, "big.csv", "a,b\n" + "1,2\n" * 400)
    with pytest.raises(R.ImportError_, match="too large"):
        R.read_any(p)


def test_malformed_json(tmp_path):
    p = _write(tmp_path, "bad.json", '{"a": [1, 2, 3], "b": [4, 5')
    with pytest.raises(R.ImportError_):
        R.read_any(p)


def test_json_with_no_arrays(tmp_path):
    p = _write(tmp_path, "scalars.json", json.dumps({"a": 1, "b": "x"}))
    with pytest.raises(R.ImportError_):
        R.read_any(p)


def test_json_datasets_block_that_is_not_an_object(tmp_path):
    p = _write(tmp_path, "blocks.json", json.dumps({"datasets": [1, 2, 3]}))
    with pytest.raises(R.ImportError_):
        R.read_any(p)


def test_npz_with_pickled_objects_is_refused(tmp_path):
    p = tmp_path / "obj.npz"
    np.savez(p, a=np.array([{"x": 1}], dtype=object))
    with pytest.raises(R.ImportError_):
        R.read_any(p)


def test_corrupt_xlsx_is_refused(tmp_path):
    p = tmp_path / "corrupt.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("not_a_workbook.txt", "hello")
    with pytest.raises(R.ImportError_):
        R.read_any(p)


def test_excel_error_cells_become_nan(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Strain (%)", "Stress (MPa)"])
    for row in ([0, 0], [1, "#DIV/0!"], [2, 0.6], [3, 0.9], [4, "#N/A"]):
        ws.append(row)
    p = tmp_path / "errors.xlsx"
    wb.save(p)
    ds = R.read_any(p)[0]
    stress = ds.column("Stress")
    assert np.isnan(stress[1]) and np.isnan(stress[4])
    assert stress[2] == pytest.approx(0.6)


# ------------------------------------------------------------------ unit mapping
@pytest.mark.parametrize("unit", ["%", "rad/s"])
def test_amplitude_sweep_accepts_a_strain_or_frequency_axis(unit):
    """The x of an amplitude/frequency sweep may be stress, strain or frequency: the
    measurement offers all three, so a % or rad/s column must not be refused."""
    m = M.get("crossover")
    cols = [[1, 10, 100], [100, 90, 10], [10, 30, 50]]
    data, _notes = M.prepare_data(m, cols, [unit, "Pa", "Pa"], {"x": 0, "g_storage": 1, "g_loss": 2})
    np.testing.assert_allclose(data["x"], [1, 10, 100])
