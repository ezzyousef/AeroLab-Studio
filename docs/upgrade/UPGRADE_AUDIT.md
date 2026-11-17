# Upgrade audit: AeroLab Studio (repository 06)

Audit of `feature/licensing` at `d0ca0dc` (v1.2.1, 121 tests passing) against the 06 brief.
Every row was checked against the code, not taken from the README. The "After" column is
the state on `upgrade/06-aerolab`.

| # | Target (06 brief) | Before | After | Evidence |
|---|---|---|---|---|
| 0 | Run the 26 baseline cases | DONE (26 cases, `validation.py`) | DONE, unchanged | `test_core.py::test_no_validation_case_fails` |
| 0 | Both documented paper discrepancies covered by tests | PARTIAL (counted, not pinned) | DONE | `tests/test_paper_discrepancies.py` |
| 0 | Real measurement-curve validations | MISSING | PARTIAL: synthetic recovery tests only | **Blocker:** no raw instrument files with known answers were supplied |
| 0 | Every metric has assumptions, units, sources | PARTIAL | DONE for units and references (tested); assumptions are in notes, the report and the studios | `test_every_demo_metric_has_a_unit…` |
| 1 | Unit dimensionality audit | MISSING | DONE: 6 mis-declared quantities fixed, SI signatures | `test_units_dimensions.py` |
| 1 | First-order assumption audit | PARTIAL (documented in a docstring) | DONE: Monte Carlo comparison reports when first order fails | `test_uncertainty.py` |
| 1 | Covariance-aware propagation, optional correlation matrix | MISSING | DONE (PSD-checked) | `core/uncertainty.py` |
| 1 | Monte Carlo cross-check | MISSING | DONE (seeded, domain-aware) | same |
| 1 | Extreme and degenerate cases vs independent calculations | PARTIAL | DONE: ρ = ±1, σ = 0, 1/x bias, failed derivative, refusal of non-PSD matrices | same |
| 2 | Sample → experiment workspace (composition, spinning, density, geometry, thermal history, instrument settings, raw attachments, replication) | MISSING | DONE | `core/workspace.py`, Workspace page |
| 2 | Chain of custody, data lineage | PARTIAL (SHA-256 in the Excel provenance) | DONE: lineage log, attachment verification | `test_workspace.py` |
| 2 | Migrations | MISSING (v1, no version check) | DONE: schema v2, v1 migrated, newer refused | same |
| 2 | Portable archives | MISSING | DONE: `.aerolabz`, verified, traversal and zip-bomb safe | same |
| 3 | Stress–strain cycles, hysteresis, energy dissipation | PARTIAL (energy for cycles 1 and last) | DONE: per-cycle loading/unloading/hysteresis, cumulative | `test_mechanics.py` |
| 3 | Fatigue S–N / strain–life comparison with bootstrap | PARTIAL (bootstrap of 2Nt only) | DONE: Basquin vs Wöhler with AIC, bootstrap intervals of all constants | same |
| 3 | Viscoelastic relaxation and creep model options | MISSING | DONE: 4 + 4 models, AIC/BIC, new measurements | same |
| 3 | Modulus interval sensitivity | MISSING | DONE | same |
| 3 | Image ↔ mechanical data linkage | MISSING | DONE (Workspace images on the run's experiment) | `test_ui_studios.py` |
| 3 | Label assumptions; no extrapolation | PARTIAL (fit curves drawn 0.5–5× outside the data) | DONE: fits stop at the tested range, extrapolated predictions flagged | `test_mechanics.py` |
| 4 | TGA/DSC multi-event integration | PARTIAL (DSC transitions list; TGA DTG peaks only) | DONE: TGA steps; DSC event table with optional crystallinity | `test_materials.py` |
| 4 | Thermal conductivity vs density | MISSING | DONE (new measurement) | same |
| 4 | BET/porosity summaries | PARTIAL | DONE: N₂ vs density pore volume | same |
| 4 | Rheology amplitude sweep | PARTIAL (crossover only) | DONE: + end of LVER | same |
| 4 | Normalised comparison between formulations | MISSING | DONE (Explorer: relative and per density) | `test_explorer.py` |
| 4 | Sample QC, flags on missing calibration | MISSING | DONE | `test_materials.py` |
| 5 | Compare batches | MISSING | DONE: t CI, Welch, ANOVA | `test_explorer.py` |
| 5 | Response surfaces | MISSING | DONE: quadratic, tested box only | same |
| 5 | Sensitivity and dimensional analysis | MISSING | DONE: elasticities, Buckingham π | same |
| 5 | DOE suggestion panel (no fabricated experiments) | MISSING | DONE: results left blank | same |
| 5 | Publishable reports with equations, provenance, citations | PARTIAL (Excel provenance sheet) | DONE: HTML and Markdown | `test_ui_studios.py` |
| 5 | Origin and Excel verification | MISSING | DONE: read-back of the workbook and the LabTalk CSVs | `test_explorer.py` |
| 6 | Task-based navigation | PARTIAL (3 groups) | DONE: Session / Analyse / Studios / Output, scrollable | `test_ui_m7.py` |
| 6 | Multi-file mapping preview | MISSING | DONE | same |
| 6 | Scientific notebook | MISSING | DONE | same |
| 6 | Graph layout templates | MISSING | DONE: overlay, 1×2, 2×1, 2×2, 2×3 with (a), (b) labels | same |
| 6 | Informative uncertainty visualisations | MISSING | DONE: MC histogram against the linear band | `test_ui_uncertainty.py` |
| 6 | Keyboard accessibility | DONE (1.2.0) | DONE: new widgets named and tab-safe (existing a11y pass applies to new pages) | `test_ui.py` |
| 6 | High-DPI scaling | PARTIAL (Qt default rounding) | DONE: PassThrough rounding | `test_ui_m7.py` |
| 6 | Long-table streaming | MISSING (40-row preview) | DONE: lazy model, 2000-row chunks | same |
| 6 | Undo | DONE (datasets, runs, calcs) | DONE: + workspace and notebook | `test_workspace.py` |

## Defects found by the new tests (each fixed after a failing test)

| Defect | Where | Test |
|---|---|---|
| BET isotherm listed high-to-low cut to one point and refused | `curves.analyze_sorption_bet` | `test_bet_surface_area_from_an_exact_isotherm[True]` |
| Crossover modulus interpolated linearly (+0.33 %) | `curves.find_moduli_crossover` | `test_crossover_point_and_modulus_on_power_laws` |
| Six physical quantities declared dimensionless; "%" scaled them by 0.01 | `equations.py` | `test_physical_quantities_declare_their_dimension` |
| wt%/phr converted 1:1 to g/L | `units.py` | `test_mass_fractions_are_not_a_mass_concentration` |
| UTF-16/32 decoded as cp1252 (NUL-filled text) | `readers._decode` | `test_utf16_and_utf32_with_bom` |
| Rows wider than the table truncated without a word | `readers._parse_delimited` | `test_a_row_wider_than_the_header_is_reported` |
| All-empty trailing column became "Column 3" | same | `test_empty_trailing_fields_do_not_create_a_phantom_column` |
| No file-size limit | `readers.read_any` | `test_oversized_file_is_refused_before_reading` |
| Amplitude-sweep x in % or rad/s refused | `measurements.prepare_data` | `test_amplitude_sweep_accepts_a_strain_or_frequency_axis` |
| Fit curves drawn beyond the tested lives | `curves.fit_sn_basquin`, `fit_strain_life` | `test_fatigue_fits_are_drawn_over_the_tested_range_only` |
| Test suite wrote to the user's real settings file | `tests/conftest.py` | autouse fixture |

## Lessons from earlier repositories, checked here

| Lesson | Result in AeroLab |
|---|---|
| Validate delimited tables at the record level | Was missing (silent truncation). Ragged rows are now reported per line in `meta["warnings"]` and on the Data page. Decision: the table keeps its modal width (not refused) so no data is lost; see the release notes. |
| Decreasing x axes | The TGA, DSC, crossover, Herschel–Bulkley, stress–strain, TGA-step and LVER analysers sort their input. BET did not handle falling pressure (fixed). Every interpolating analyser is tested in both orders. |
| Areas integrate the full function | DSC already integrated against a full-width chord. Recovery tests on Gaussians confirm it to within 2 %. The hysteresis area is checked analytically. |
| Headless Qt fixtures delete windows | Not done before. An autouse fixture now closes and deletes windows, and the suite went from 230 s to about 130 s. |
