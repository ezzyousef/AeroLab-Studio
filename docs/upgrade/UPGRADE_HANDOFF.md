# Handoff: AeroLab Studio upgrade (repository 06)

| | |
|---|---|
| Local path | `E:\Lab Apps\AeroLab_Studio` |
| Branch | `upgrade/06-aerolab`, from `feature/licensing` at `d0ca0dc`; pushed to origin |
| Version | 1.2.1 → 1.3.0 (`aerolab/__init__.py`, `installer/AeroLabStudio.iss`) |
| Tests | `QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg py -3 -m pytest -q -p no:cacheprovider`: **374 passed** (121 at baseline) |
| Installer | Not rebuilt in this round |
| Merge | **Not merged**; that is the owner's decision |

## Feature matrix (brief → now)

| # | Target | Now | Blocker / note |
|---|---|---|---|
| A | Equation oracles + report | **DONE** | 59/59 equations; `docs/EQUATION_REGRESSION_REPORT.md` |
| A | Hostile files for every importer | **DONE** | 24 tests; 5 reader defects fixed |
| 0 | Both paper discrepancies in tests | **DONE** | |
| 0 | Real measurement-curve validations | **PARTIAL** | **Blocker:** no raw instrument curves with known answers were supplied. The recovery tests are synthetic |
| 1 | Units, covariance, Monte Carlo, degenerate cases | **DONE** | |
| 2 | Workspace, lineage, migrations, archives | **DONE** | |
| 3 | Mechanics studio (cycles, fatigue comparison + bootstrap, viscoelastic, modulus sensitivity, image link, no extrapolation) | **DONE** | Relaxation and creep demos are SYNTHETIC: no such data came with the papers |
| 4 | Materials studio (TGA/DSC events, k–ρ, BET/porosity, rheology, normalised comparison, QC/calibration flags) | **DONE** | Crystallinity needs a user ΔH°m |
| 5 | Explorer (batches, response surface, sensitivity and π, DOE, report, Origin/Excel verification) | **DONE** | Live Origin verification **BLOCKED**: Origin is not installed here. The LabTalk package is verified |
| 6 | UI (task navigation, mapping preview, notebook, layouts, uncertainty plots, keyboard, high DPI, streaming, undo) | **DONE** | Screen-reader pass with NVDA not run |

## Defects fixed (each after a failing test)

These were found by the new tests and fixed in source:

- BET falling-order input: `aerolab/core/curves.py` (`analyze_sorption_bet`, branch detection).
- Crossover modulus: log interpolation in `find_moduli_crossover`.
- Six unit declarations: `aerolab/core/equations.py`. New dimensions and wt%/phr in `aerolab/core/units.py`.
- `aerolab/io/readers.py`: UTF-16/32 handling (`_decode`); ragged-row warnings (`_shape_warnings`); empty trailing columns (`_drop_empty_trailing_fields`); `MAX_FILE_BYTES`; JSON block check.
- Sweep x in % or rad/s: `Channel.alt_dimensions` in `aerolab/core/measurements.py`.
- Fit curves beyond the data, and extrapolation flags: `fit_sn_basquin`, `fit_strain_life`.

## Rollback

- Whole upgrade: `git switch feature/licensing`. That branch is unchanged and pushed.
- One milestone: `git revert <hash>`. The hashes are listed in `UPGRADE_IMPLEMENTATION_PLAN.md`.
- Session files: 1.3 writes schema 2, and 1.2 ignores the workspace and notebook in them. Keep copies of
  important `.aerolab` files before downgrading.

## Next steps

1. The owner supplies real exports with known answers (a tensile pull with an extensometer
   modulus, a certified BET reference, an indium DSC run) so recovery can be tested on real data.
2. Rebuild with `build.ps1` / `pyinstaller AeroLabStudio.spec`, then smoke-test the installer.
   This includes the `.aerolabz` association.
3. Run an independent read-only Codex review of `d0ca0dc..upgrade/06-aerolab`.
4. Decide whether ragged rows should be refused (as FTIR does) instead of reported.
5. Next repository in the queue: 07 `Figure-Studio`.
