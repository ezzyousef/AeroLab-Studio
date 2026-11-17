# Test report: upgrade 06

Command (repository root, PowerShell or Git Bash):

```
QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg py -3 -m pytest -q -p no:cacheprovider
```

Environment: Windows 11, Python 3.14, PySide6 6.11, offscreen Qt.

| Point | Result | Time |
|---|---|---|
| Baseline `feature/licensing` `d0ca0dc` | **121 passed** | 231 s |
| After M1 | 275 passed | 130 s |
| After M2 | 294 passed | 120 s |
| After M3 | 324 passed | 128 s |
| After M4 | 342 passed | 164 s |
| After M5 | 355 passed | 491 s (machine shared with other agents) |
| After M6 | 368 passed | 218 s |
| Final (M7) | **374 passed**, 0 failed, 0 skipped | 232 s |

No test was skipped, deleted or weakened. One existing assertion pattern was extended, not
relaxed: `conftest.py` gained two autouse fixtures (settings isolation and window deletion).

## New test files

| File | Tests | What it proves |
|---|---|---|
| `test_equation_oracles.py` | 84 | 59/59 equations against independent SI arithmetic, 16 hand values, limits and identities (consistency) |
| `test_curve_oracles.py` | 17 | Analysers recover known truth in both axis orders: BET, Gurvich, DSC, TGA, hysteresis, toughness, modulus, crossover, HB, Basquin, thermal (recovery) |
| `test_paper_discrepancies.py` | 6 | Both documented disagreements with the papers are pinned; every metric has a unit, every case a source |
| `test_units_dimensions.py` | 23 | Dimensionality audit, new dimensions, SI signatures, calculator conversion |
| `test_import_hostile.py` | 24 | Ragged rows, title lines, trailing fields, decimal comma, UTF-16/32, NaN rows, quoted thousands, CR line endings, binary garbage, header-only, prose, oversize, malformed JSON, pickled NPZ, corrupt XLSX, Excel error cells, sweep units |
| `test_uncertainty.py` | 14 | Covariance against closed forms; ρ = ±1, σ = 0, non-PSD refusal; Monte Carlo against linear; Jensen bias of 1/x; domain rejection; reproducibility |
| `test_ui_uncertainty.py` | 5 | Calculator dialog, MC panel, stale-result clearing, session round trip, Excel method column |
| `test_workspace.py` | 30 | Records, derived values, refusals, replicates, t CI, lineage, attachment change detection, migration v1→v2, newer-schema refusal, archive round trip, tamper/traversal/zip-bomb refusal, no overwrite, undoable session edits, the page end to end |
| `test_mechanics.py` | 15 | Window sensitivity, S–N model choice and bootstrap coverage, strain–life bootstrap, no extrapolation, cycle energies, SLS/Prony/Burgers/KV recovery, assumptions |
| `test_materials.py` | 12 | TGA steps (both orders), DSC table, k–density minimum only inside the range, porosity summary, LVER (both orders), QC rules incl. stale/future calibration |
| `test_explorer.py` | 12 | Welch and ANOVA, normalised comparison, exact response surface, elasticities, π groups, DOE designs, Excel/Origin read-back and tamper detection |
| `test_ui_studios.py` | 5 | Mechanics, Materials and Explorer pages headless (incl. HTML escaping of the report) |
| `test_ui_m7.py` | 6 | Notebook, streaming model (300 000 rows), mapping overview, layout templates, navigation, high-DPI policy in a fresh interpreter |

## Screenshots

These are from the real app, headless, with `QT_QPA_FONTDIR=C:\Windows\Fonts`:
`docs/upgrade/screenshots/{data,workspace,mechanics,materials,explorer}.png`. The first set
showed two problems. Five new navigation glyphs drew as empty boxes, so they were replaced
by characters that common fonts have. On a 900 px window the Workspace page squeezed the
experiment form over its table, so the page now scrolls instead.

## Not run / not verified

- **PyInstaller build and installer**: not rebuilt. `hiddenimports` needed no change: the new
  code uses scipy.optimize, scipy.stats and zipfile only, and the earlier build already
  bundled all of these. Unverified until the next build.
- **Real instrument files**: none supplied, so the recovery tests are synthetic.
- **Origin live automation**: Origin is not installed here. The LabTalk package path is
  verified by read-back.
- **Screen reader**: the accessible names are set and tested. NVDA/Narrator were not run.
- **Independent review (Codex)**: NOT RUN in this round.
