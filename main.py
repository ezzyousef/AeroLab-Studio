"""AeroLab Studio — application entry point.

    python main.py                 start the app
    python main.py data.csv ...    start and import those files
    python main.py --selftest      check this build without opening a window
    python main.py --version       print the version and exit
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the package importable when run from a frozen build or another directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def selftest() -> int:
    """Exercise the whole stack headlessly. Used to verify a packaged build."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["MPLBACKEND"] = "Agg"
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        print(f"{'ok  ' if condition else 'FAIL'}  {label}{'' if condition else '  ' + detail}")
        if not condition:
            failures.append(label)

    try:
        from aerolab import __version__
        from aerolab.core import equations as E, measurements as M, validation as V
        from aerolab.io import excel as X, origin as O, readers as R
        from aerolab.viz import figures as F
        print(f"AeroLab Studio {__version__}   ({'frozen' if getattr(sys, 'frozen', False) else 'source'} build)\n")
    except Exception as exc:                                # noqa: BLE001
        print(f"FAIL  imports: {exc}")
        return 1

    check(f"{len(E.REGISTRY)} equations loaded", len(E.REGISTRY) >= 59)
    check(f"{len(M.MEASUREMENTS)} measurements loaded", len(M.MEASUREMENTS) >= 11)

    summary = V.summary()
    check(f"validation: {summary['reproduced']} reproduced, "
          f"{summary['documented_discrepancies']} documented, {summary['failed']} failed",
          summary["failed"] == 0)

    # The Data page resolves the samples from its own location, so check *that* path
    # rather than recomputing one here — they differ in a frozen build, and "Load demo
    # data" is the first button anyone presses.
    from aerolab.ui.pages.data import SAMPLES_DIR as samples
    check(f"demo datasets found at {samples}", samples.is_dir())
    check(f"{len(list(samples.glob('*.csv')))} demo CSVs present",
          len(list(samples.glob("*.csv"))) >= 11)

    results = {}
    if samples.is_dir():
        for measurement in M.MEASUREMENTS:
            try:
                dataset = R.read_any(samples / measurement.sample)[0]
                mapping = measurement.match_columns(dataset.headers)
                if measurement.kind == "table":
                    rows = [{k: float(dataset.columns[v][i]) for k, v in mapping.items()
                             if v is not None} for i in range(dataset.n_rows)]
                    results[measurement.id] = measurement.run_table(rows)[0]
                else:
                    results[measurement.id] = measurement.run(
                        {k: dataset.columns[v] for k, v in mapping.items() if v is not None})
            except Exception as exc:                        # noqa: BLE001
                check(f"analyse {measurement.id}", False, str(exc))
        check(f"{len(results)}/{len(M.MEASUREMENTS)} measurements analysed",
              len(results) == len(M.MEASUREMENTS))

    try:
        drawn = 0
        for measurement in M.MEASUREMENTS:
            if measurement.id not in results:
                continue
            for plot in measurement.plots:
                data = F.build_plot_data(plot, results[measurement.id])
                if not data.is_empty:
                    F.render_figure(data)
                    drawn += 1
        check(f"{drawn} figures rendered", drawn >= 12)
    except Exception as exc:                                # noqa: BLE001
        check("figures rendered", False, str(exc))

    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            report = X.ExcelReport(project="self-test", validation=V.run_all())
            for mid, result in results.items():
                report.add(X.RunRecord(mid, M.get(mid), result))
            path = X.write_workbook(report, Path(tmp) / "selftest.xlsx")
            check(f"Excel workbook written ({path.stat().st_size // 1024} kB)",
                  path.stat().st_size > 20_000)

            items = [O.OriginExportItem(mid, M.get(mid), result)
                     for mid, result in results.items() if M.get(mid).plots]
            package = O.write_script_package(items, Path(tmp) / "origin")
            check(f"Origin script package written ({package.graphs} graphs)",
                  (Path(tmp) / "origin" / "AeroLab_build.ogs").exists())
    except Exception as exc:                                # noqa: BLE001
        check("exports", False, str(exc))

    ok, why = O.origin_available()
    print(f"note  OriginLab automation: {why}")

    try:
        from PySide6.QtWidgets import QApplication
        from aerolab.ui.app import PAGES, MainWindow, _app_icon
        from aerolab.ui.state import Session

        app = QApplication.instance() or QApplication([])
        window = MainWindow(Session())
        window.show()
        app.processEvents()
        visited = 0
        for key in window.pages:
            window.go_to(key)
            app.processEvents()
            visited += window.stack.currentWidget() is window.pages[key]
        check(f"interface opened, {visited} of {len(PAGES)} pages visited",
              visited == len(PAGES))
        icon = _app_icon()
        check(f"application icon loaded ({len(icon.availableSizes())} sizes)",
              not icon.isNull())
        window.close()
    except Exception as exc:                                # noqa: BLE001
        check("interface", False, str(exc))

    # Plain ASCII from here: a frozen console on Windows uses the legacy code page, and a
    # dash or an arrow comes out as a replacement character.
    print()
    if failures:
        print(f"SELF-TEST FAILED - {len(failures)} problem(s): {', '.join(failures)}")
        return 1
    print("SELF-TEST PASSED - this build is working.")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--version" in argv or "-V" in argv:
        from aerolab import __version__
        print(f"AeroLab Studio {__version__}")
        return 0
    if "--selftest" in argv:
        return selftest()

    # matplotlib must use the Qt backend before anything imports pyplot.
    os.environ.setdefault("MPLBACKEND", "QtAgg")
    try:
        from aerolab.ui.app import run
    except ImportError as exc:                    # a missing dependency should say which
        sys.stderr.write(
            f"AeroLab Studio could not start: {exc}\n\n"
            "Install the requirements with:\n    pip install -r requirements.txt\n")
        return 2
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
