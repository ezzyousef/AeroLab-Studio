# Implementation plan and record: upgrade 06

The work ran in milestones on `upgrade/06-aerolab`, which was branched from `feature/licensing` at `d0ca0dc`.
Before each commit the whole suite was green.

| Milestone | Commit | Content | Tests after |
|---|---|---|---|
| M1 Correctness | `8e7f455` | Equation oracles (59/59), curve recovery in both axis orders, unit audit, hostile-import hardening, paper-discrepancy tests, settings isolation and window clean-up in the tests | 275 |
| M2 Uncertainty | `81e6926` | `core/uncertainty.py` (covariance, PSD check, Monte Carlo), Calculator dialog and histogram, export of the method | 294 |
| M3 Workspace | `47ed4f2` | `core/workspace.py`, session schema v2 with migration, `.aerolabz` archives, Workspace page, undoable edits | 324 |
| M4 Mechanics | `8c06387` | `core/mechanics.py`, relaxation and creep measurements (SYNTHETIC demos), no-extrapolation fits, Mechanics studio | 342 |
| M5 Materials | `acf6895` | `core/materials.py`, k–density measurement, TGA steps, LVER, QC flags, Materials studio | 355 |
| M6 Explorer | `da4e8f8` | `core/explorer.py`, `io/report.py`, Explorer page, streaming preview, all-files mapping overview | 368 |
| M7 UI and release | see `git log` | Notebook, layout templates, task-grouped scrollable navigation, high DPI, `.aerolabz` association, version 1.3.0, docs | see the test report |

## Design choices and trade-offs

- **No new framework or dependency.** All new science uses NumPy and SciPy, which were already
  required. labkit was not vendored, because no target needed it: the licence module stays
  the only vendored code.
- **Plain-data core, thin pages.** Each feature is a Qt-free module (`uncertainty`, `workspace`,
  `mechanics`, `materials`, `explorer`, `report`) with its own tests. The pages only call
  into them.
- **Copy-on-write workspace.** `Session.edit_workspace` applies a change to a copy and keeps the
  copy only if the change succeeds. Undo snapshots hold references, so undo stays cheap and
  a failed edit leaves nothing behind. The cost is one deep copy per edit, which is small at
  realistic sizes (a few hundred records).
- **Schema v2 is additive.** v1 files open (migrated, with a lineage entry), and readers ignore
  unknown fields, so a 1.3 file stays readable as more fields are added. A file with a
  higher schema number is refused, not half-read.
- **Ragged rows are reported, not refused.** FTIR chose to refuse them. Here the modal width is
  kept and every non-conforming row is listed, which avoids blocking real instrument
  exports that have a stray trailing field. It is recorded as a decision, so it can be
  revisited.
- **No extrapolation.** Fit curves are drawn over the calibration range only, and predictions
  outside it carry an explicit flag.
- **Nothing fabricated.** DOE returns settings with blank results. Crystallinity needs a
  user-entered ΔH°m. The two new demo files say SYNTHETIC in their header and are made by
  `build_assets/make_synthetic_samples.py`.

## Maintenance cost

About 4,700 new lines of source and 2,100 of tests. The cost is concentrated in five
modules with no coupling between them, apart from `curves.py` calling `mechanics` and
`materials` lazily for the sensitivity, TGA-step and LVER metrics.
