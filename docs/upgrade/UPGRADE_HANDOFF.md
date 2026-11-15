# Handoff: AeroLab Studio upgrade (repository 06)

| | |
|---|---|
| Local path | `E:\Lab Apps\AeroLab_Studio` |
| Branch | `upgrade/06-aerolab`, from `feature/licensing` at `d0ca0dc`; pushed to origin |
| Version | 1.2.1 → 1.3.0 (`aerolab/__init__.py`, `installer/AeroLabStudio.iss`) |
| Tests | `QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg py -3 -m pytest -q -p no:cacheprovider`: **393 passed** (121 at baseline; 374 before the Codex fixes) |
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

## Codex review (independent, read-only)

The review is at `AI_Engineering_Knowledge_Base/reports/codex/06-aerolab-upgrade-review.md` and
covers `bda8754`. It found 3 high and 4 medium issues, and all 7 reproduced. Each one has
regression tests in `tests/test_codex_review.py`, built from the reviewer's input. 16 of
those tests fail on `bda8754`. The other 2 pass there by design, because they are guards
(trailing empty fields are still accepted; the BET branch option is saved with the run).

| Severity | Finding | Fix | Tests |
|---|---|---|---|
| High | Archive collision fallback skipped the hash, containment and link checks | `workspace._place_attachment` checks every candidate name for containment, link status and SHA-256, and creates the file with `O_EXCL`/`O_NOFOLLOW` | `test_codex1_collision_fallback_is_hash_checked`, `…link_candidate_is_skipped…`, `…created_exclusively` |
| High | First (headerless) row and wide rows truncated into the analysis | `readers._parse_delimited` validates every record. A row wider than the header (or than the modal width when there is no header) refuses the file with its line numbers. Only empty trailing fields are dropped. Excel no longer pads or truncates. | `test_codex2_*` (4) |
| High | NPZ/XLSX could expand far beyond the 256 MB file limit | `MAX_UNCOMPRESSED_BYTES` (zip member sizes) is checked before loading. NPZ `.npy` headers are read for a value budget, and XLSX is held to a cell budget (`MAX_VALUES`). | `test_codex3_*` (4) |
| Medium | Monte Carlo kept physically invalid draws | `uncertainty.lower_bound` (non-negative dimensions, absolute zero) and `DOMAIN_RULES` (ρb ≤ ρs and others) are applied to every draw and to the nominal values (`check_domain`) | `test_codex4_*` (2) |
| Medium | `compare()` reported agreement when the linear σ was 0 or NaN | Explicit `status`: unavailable / disagree / exact / agree | `test_codex5_…` |
| Medium | Descending-only BET was assumed to be adsorption | New `branch` option (auto/adsorption/desorption). Descending-only input under "auto" is refused. The choice is kept in the run options and the result meta. | `test_codex6_*` (2) |
| Medium | Runs of the same file and measurement shared one workspace key | `Run.uid` is persisted in the session. Legacy links move to the new id only when unambiguous; ambiguous ones are logged and left in place. | `test_codex7_*` (2) |

Two tests written earlier in this upgrade expected rows wider than the header to be kept
and reported. They now expect the file to be refused
(`test_a_row_wider_than_the_header_is_refused_with_its_line`,
`test_every_row_wider_than_the_header_is_refused`), which is the rule the review asked for.
A new test checks that short rows are still kept.
