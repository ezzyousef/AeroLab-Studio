"""Measurements, figures and a headless run of the interface."""
from __future__ import annotations

import numpy as np
import pytest

from aerolab.core import measurements as M
from aerolab.io import readers as R
from aerolab.viz import figures as F, style as S


# ------------------------------------------------------------------ measurements
def test_registry_is_well_formed():
    assert len(M.MEASUREMENTS) >= 11
    ids = [m.id for m in M.MEASUREMENTS]
    assert len(ids) == len(set(ids))
    for measurement in M.MEASUREMENTS:
        assert measurement.channels, measurement.id
        assert measurement.summary and measurement.reference
        assert callable(measurement.analyser)
        for plot in measurement.plots:
            assert plot.series, f"{measurement.id}/{plot.id} has no series"
            assert plot.xscale in ("linear", "log")
            assert plot.yscale in ("linear", "log")


def test_every_measurement_has_its_demo_file(samples_dir):
    for measurement in M.MEASUREMENTS:
        assert (samples_dir / measurement.sample).exists(), measurement.sample


def test_column_matching_skips_irrelevant_columns():
    measurement = M.get("stress_strain")
    mapping = measurement.match_columns(["Time (s)", "Tensile strain (%)",
                                         "Tensile stress (MPa)"])
    assert mapping["strain_pct"] == 1 and mapping["stress_mpa"] == 2


def test_column_matching_does_not_let_one_channel_steal_another():
    measurement = M.get("crossover")
    mapping = measurement.match_columns(["Shear stress (Pa)", "G' (Pa)", "G'' (Pa)"])
    assert mapping["g_storage"] == 1 and mapping["g_loss"] == 2


def test_missing_required_column_is_refused():
    measurement = M.get("stress_strain")
    with pytest.raises(ValueError, match="missing required"):
        measurement.run({"strain_pct": np.linspace(0, 10, 20)})


def test_measurement_search():
    assert [m.id for m in M.search("fatigue")]
    assert M.search("") == list(M.MEASUREMENTS)


# ------------------------------------------------------------------------ figures
def test_palette_is_distinct_and_valid():
    for name, colours in S.PALETTES.items():
        assert len(colours) >= 6, name
        assert len(set(colours)) == len(colours), f"{name} repeats a colour"
        for colour in colours:
            assert colour.startswith("#") and len(colour) == 7, f"{name}: {colour}"


def test_neighbouring_series_differ_in_shape_and_colour():
    styles = [S.style_for(i, "data") for i in range(6)]
    assert len({s.colour for s in styles}) == 6
    for a, b in zip(styles, styles[1:]):
        assert a.symbol != b.symbol


def test_origin_symbol_interior_is_filled_for_filled_series():
    """Origin's enum is 0 = filled, 1 = open — the opposite of originpro's docstring."""
    filled = S.style_for(0, "data")
    assert filled.filled is True
    assert filled.origin_symbol_interior == 0
    open_style = S.SeriesStyle("#0072B2", "circle", "none", 0, 6, False)
    assert open_style.origin_symbol_interior == 1


def test_fit_borrows_its_parent_colour(analysed):
    measurement = M.get("strain_life")
    plot = measurement.plots[0]
    data = F.build_plot_data(plot, analysed["strain_life"])
    by_label = dict(zip(data.labels, data.styles))
    assert by_label["Elastic branch"].colour == by_label["Elastic, measured"].colour
    assert by_label["Plastic branch"].colour == by_label["Plastic, measured"].colour
    assert by_label["Elastic branch"].colour != by_label["Plastic branch"].colour


def test_log_axis_falls_back_when_data_is_not_positive():
    from aerolab.core.curves import AnalysisResult
    from aerolab.core.measurements import Plot, Series
    plot = Plot("p", "t", "x", "", "y", "", (Series("d", "d", "scatter"),),
                xscale="log", yscale="log")
    result = AnalysisResult("x", [], {"d": (np.array([-1.0, 1, 2]), np.array([1.0, 2, 3]))})
    assert F.build_plot_data(plot, result).xscale == "linear"


def test_every_plot_renders_in_both_themes(analysed):
    for measurement in M.MEASUREMENTS:
        result = analysed[measurement.id]
        if isinstance(result, list):
            continue
        for plot in measurement.plots:
            for theme in ("light", "dark"):
                data = F.build_plot_data(plot, result, theme=theme)
                assert not data.is_empty, f"{measurement.id}/{plot.id}"
                figure = F.render_figure(data, theme=theme)
                assert figure.axes


def test_figure_saves_to_disk(tmp_path, analysed):
    measurement = M.get("stress_strain")
    data = F.build_plot_data(measurement.plots[0], analysed["stress_strain"])
    figure = F.render_figure(data)
    path = F.save_figure(figure, tmp_path / "fig.png", dpi="screen")
    assert path.exists() and path.stat().st_size > 5_000


def test_free_corners_avoids_the_data(analysed):
    """A rising curve fills the lower-left and upper-right; boxes belong elsewhere."""
    from aerolab.core.curves import AnalysisResult
    from aerolab.core.measurements import Plot, Series
    x = np.linspace(0, 10, 200)
    plot = Plot("p", "t", "x", "", "y", "", (Series("d", "d", "line"),))
    result = AnalysisResult("x", [], {"d": (x, x)})
    corners = F.free_corners(F.build_plot_data(plot, result))
    assert corners[0] in ("upper left", "lower right")


# --------------------------------------------------------------------- interface
def test_session_undo_redo(qapp):
    from aerolab.ui.state import Session
    from aerolab.core.curves import AnalysisResult

    session = Session()
    assert not session.can_undo() and not session.can_redo()

    measurement = M.get("stress_strain")
    empty = AnalysisResult("stress_strain", [], {})
    session.add_run("a", measurement, empty)
    session.add_run("b", measurement, empty)
    assert len(session.runs) == 2 and session.can_undo()
    assert "b" in session.undo_label()

    session.undo()
    assert [r.sample for r in session.runs] == ["a"]
    session.undo()
    assert not session.runs and session.can_redo()
    session.redo()
    assert [r.sample for r in session.runs] == ["a"]

    session.add_run("c", measurement, empty)               # a new action clears the tail
    assert not session.can_redo()


def test_session_save_and_load(qapp, tmp_path, analysed):
    from aerolab.ui.state import Session

    session = Session()
    for measurement in M.MEASUREMENTS:
        result = analysed[measurement.id]
        if not isinstance(result, list):
            session.add_run(measurement.sample, measurement, result)
    before = len(session.runs)

    path = session.save_project(tmp_path / "s.aerolab")
    assert path.exists()

    reopened = Session()
    assert reopened.load_project(path) == before
    assert len(reopened.runs) == before
    assert reopened.runs[0].result.metrics


def test_main_window_visits_every_page(qapp):
    from aerolab.ui.app import MainWindow
    from aerolab.ui.state import Session

    errors: list[str] = []
    session = Session()
    session.status.connect(lambda m, level: errors.append(m) if level == "error" else None)

    window = MainWindow(session)
    window.show()
    qapp.processEvents()

    window.pages["data"].load_samples()
    qapp.processEvents()
    assert len(session.datasets) >= 11

    data_page = window.pages["data"]
    for i in range(len(session.datasets)):
        data_page.file_list.setCurrentRow(i)
        qapp.processEvents()
        if data_page.btn_analyse.isEnabled():
            data_page.analyse_current()
        qapp.processEvents()
    assert len(session.runs) >= 10
    assert not errors, errors[:3]

    for theme in ("dark", "light"):
        session.set_setting("theme", theme)
        for key in window.pages:
            window.go_to(key)
            qapp.processEvents()
            assert window.stack.currentWidget() is window.pages[key]

    window.close()


def test_about_page_carries_the_author_details(qapp):
    from aerolab.ui.pages.about import AboutPage, AUTHOR, EMAIL, LAB
    from aerolab.ui.state import Session

    page = AboutPage(Session())
    qapp.processEvents()
    text = " ".join(label.text() for label in page.findChildren(type(page._title)))
    assert AUTHOR in text
    assert EMAIL in text
    assert LAB in text


def test_application_icon_has_every_taskbar_size(qapp):
    from aerolab.ui.app import _app_icon, app_pixmap

    icon = _app_icon()
    assert not icon.isNull()
    sizes = {s.width() for s in icon.availableSizes()}
    assert {16, 32, 48, 256} <= sizes, f"missing taskbar sizes, got {sorted(sizes)}"
    assert not app_pixmap(64).isNull()


def test_help_and_file_menu_actions_do_not_raise(qapp, monkeypatch):
    """These slots are never reached by a page-visit test, and one of them once crashed."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from aerolab.ui.app import MainWindow
    from aerolab.ui.state import Session

    monkeypatch.setattr(QMessageBox, "about", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))

    window = MainWindow(Session())
    window.show()
    qapp.processEvents()
    window.show_about()
    window.open_guide()
    window.save_session()
    window.open_session()
    window.undo()
    window.redo()
    window.toggle_theme()
    window.close()


def test_every_command_palette_entry_is_callable(qapp, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from aerolab.ui.app import MainWindow
    from aerolab.ui.state import Session
    from aerolab.ui.widgets import CommandPalette

    monkeypatch.setattr(QMessageBox, "about", staticmethod(lambda *a, **k: None))
    for name in ("getOpenFileName", "getSaveFileName"):
        monkeypatch.setattr(QFileDialog, name, staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))

    window = MainWindow(Session())
    window.show()
    qapp.processEvents()
    window.show_palette()
    palette = [w for w in qapp.topLevelWidgets() if isinstance(w, CommandPalette)][-1]
    commands = list(palette._commands)
    palette.close()
    assert len(commands) >= 20

    slow = {"Load demo datasets", "Analyse all imported datasets", "Re-run validation"}
    for label, _group, fn in commands:
        if label in slow:
            continue
        fn()
        qapp.processEvents()
    window.close()


def test_calculator_computes_every_equation_from_its_defaults(qapp):
    from aerolab.ui.pages import CalculatorPage
    from aerolab.ui.state import Session

    page = CalculatorPage(Session())
    blank = []
    for i in range(page.eq_list.count()):
        page.eq_list.setCurrentRow(i)
        qapp.processEvents()
        if page.result_label.text() == "—":
            blank.append(page.eq_list.item(i).text().split("\n")[0])
    assert not blank, f"these equations showed no result: {blank}"


def test_analyse_all_runs_every_demo_and_skips_unidentified(qapp, tmp_path):
    from aerolab.ui.app import MainWindow
    from aerolab.ui.state import Session

    messages: list[tuple[str, str]] = []
    session = Session()
    session.status.connect(lambda m, level: messages.append((m, level)))
    window = MainWindow(session)
    data_page = window.pages["data"]
    data_page.load_samples()
    n_demo = len(session.datasets)
    odd = tmp_path / "mystery.csv"
    odd.write_text("a,b\n1,2\n2,3\n3,5\n4,4\n", encoding="utf-8")
    from aerolab.io import readers as R
    session.add_datasets(R.read_any(odd))
    qapp.processEvents()
    data_page.analyse_all()
    qapp.processEvents()
    assert not [m for m, level in messages if level == "error"], messages
    assert all(r.dataset_name != "mystery" for r in session.runs)
    assert len({r.dataset_name for r in session.runs}) >= n_demo - 1
    window.close()


def test_calculator_converts_a_temperature_uncertainty(qapp):
    from aerolab.core import equations as E
    from aerolab.ui.app import MainWindow
    from aerolab.ui.state import Session

    window = MainWindow(Session())
    calc = window.pages["calculator"]
    calc._show_equation(E.get("mean_free_path"))
    value_edit, unit_combo, sigma_edit = calc._inputs["T"]
    unit_combo.setCurrentText("°F")
    value_edit.setText("77")
    sigma_edit.setText("9")                 # 9 °F = 5 K
    qapp.processEvents()
    text = calc.result_label.text()
    assert "±" in text, text
    value, sigma = (float(t.split()[0]) for t in text.split("±"))
    assert abs(sigma / value - 5 / 298.15) < 0.02
    window.close()
