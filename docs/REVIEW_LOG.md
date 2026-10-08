# Review log

Two independent reviews of AeroLab Studio were run. One covered the science and
statistics; the other covered code, data handling, user experience and exports. This file
lists what they found and what was done about each finding. Line numbers refer to the
code as it was reviewed.

Status:
- **fixed**: changed, with a test where one could be written.
- **changed wording**: the behaviour stays the same, but the documentation or labels now
  say what it does.
- **open**: not addressed in this round, with the reason.

## Analyses (core/curves.py)

| Finding | Status |
|---|---|
| S–N and strain–life regressed stress on life. ASTM E739 regresses log life on log stress (or strain), because the scatter is in life. Regressing the other way biases the exponent towards zero. | **fixed**: E739 direction, then inverted. Standard errors use the delta method; 95 % intervals use t with n−2 degrees of freedom. |
| No uncertainty on the fatigue constants or the transition life | **fixed**: SE and 95 % CI for σ′f, b, ε′f, c; bootstrap percentile interval for 2Nt |
| Curves plotted against N with the axis labelled 2N | **fixed**: curves are on reversals 2N |
| Modulus window was chosen on noisy data and could pick a 3-point spike | **fixed**: windows must span ≥ 0.5 % strain. The most linear window is chosen among those with slope ≥ 70 % of the steepest. The search is vectorised. |
| Elongation at break taken at the last data point, including the post-break tail | **fixed**: last point before stress falls below 10 % of UTS |
| 0.2 % offset yield always reported, meaningless for elastomers and foams | **fixed**: offset 0 switches it off. The help text says when to do that. |
| "Specific strength" metric had no density input | **fixed**: removed |
| DSC `exo_up` option inverted the sign convention it described | **fixed**: renamed to "Endotherms point up (exo down)". Sessions saved with `exo_up` are translated, so they give the same numbers. |
| DSC enthalpy NaN or wrong on broad, noisy melts (13 of 40 synthetic runs) | **fixed**: the peak-limit walk now starts outside the rounded tip. Now 0 of 40 runs fail, and the median is within 0.1 % of the true area. |
| DSC reported 0 when no transition was found | **fixed**: NaN |
| DSC in mW could not be normalised | **fixed**: sample-mass option |
| BET used the desorption branch when present | **fixed**: only adsorption up to the pressure maximum |
| BET never checked the Rouquerol criteria; a negative C was reported | **fixed**: criteria checked and problems listed. An optional automatic range is available. A non-physical fit is refused, with a Type I hint. SEs are given for area and Vm. |
| Gurvich point read from the nearest point, even past the end of the isotherm | **fixed**: interpolated; NaN if the isotherm stops short |
| TGA failed on repeated temperatures | **fixed**: duplicates averaged |
| No dry-basis option for TGA | **fixed** |
| Herschel–Bulkley fitted unweighted, so the high-rate points dominated | **fixed**: relative weighting, with SEs for τy, K and n |
| Power-law exponent CI used z = 1.96 | **fixed**: t-quantile |
| Reference exponents shown as if they were results | **fixed**: moved to the note |

## Import (io/readers.py, core/measurements.py, ui/pages/data.py)

| Finding | Status |
|---|---|
| Units read from headers were never applied. A kPa column was analysed as MPa. | **fixed**: converted to each channel's unit. A column of the wrong quantity (N for stress) is refused. |
| `load` and `displacement` were aliases for stress and strain | **fixed**: removed (they are force and length) |
| Unmatched channels silently filled by column order | **fixed**: flagged as guessed in the table and the pill |
| One- and two-letter headers matched as substrings ("a" matched "tensile strain") | **fixed**: exact matches only |
| "Analyse all" ran files whose measurement was a guess | **fixed**: only clearly identified files are run; the rest are listed |
| Preamble lines without a comment character were taken as the header | **fixed** |
| `1.5e-3` in a comma-decimal file read as 0.015; `1,5` in a point-decimal file read as 15 | **fixed**: only unambiguous thousands grouping is stripped |
| Whitespace headers with units split into extra columns | **fixed** |
| A workbook with a chartsheet failed to import; `.xls` failed with a cryptic error | **fixed** |

## Interface

| Finding | Status |
|---|---|
| Plots page: series with the same sample name overwrote each other (strain–life elastic and plastic, two runs of one sample) | **fixed** |
| Settings tab showed defaults, not the settings the run used | **fixed** |
| After changing a setting, the old results showed with no warning | **fixed**: an amber note shows until re-run |
| Window could not be made smaller than about 1100×850; cards squashed | **fixed**: minimum 960×600, and pages scroll |
| Mapping table too narrow to read the chosen column | **fixed** |
| Toasts clipped their own text | **fixed** |
| White boxes behind the summary tile labels | **fixed** |
| Fit range not drawn on every graph (for example the BET window on the isotherm) | **fixed**: the modulus window, the BET range (on both the isotherm and the BET plot) and the DSC peak integration limits are shaded and named in the legend |
| Dark-mode contrast of some muted text | **fixed**: every text/background pair was measured against WCAG AA (4.5:1). Muted text already passed. Two pairs failed in dark mode: white text on the accent colour (3.6:1) and accent-coloured text on raised panels (4.4:1). Both were fixed with a lighter accent and dark text on accent buttons. A test now checks these pairs. |
| (found while checking) After "Analyse all", leftover column pickers piled up in the mapping table | **fixed** |

## Validation and claims

| Finding | Status |
|---|---|
| The "Published" column showed the app's own value for cases where the paper prints none, or prints a different number | **fixed**: columns are now Reference / Paper prints / Basis. The tiles count printed values (17/17) separately from other checks (7). |
| README said "every relation in the three papers" and "self-validation" | **changed wording** |
| User guide said propagation made "no assumption that the equation is linear" | **changed wording**: the guide now says it is first-order, linearised propagation that treats the inputs as independent |

The basis of each case comes from the case's own source annotation in `core/validation.py`. The cited papers were not re-read for this review. The 17 cases labelled "paper" therefore rest on those annotations.

## Calculator and uncertainty

| Finding | Status |
|---|---|
| A failed derivative counted as 0, so the result showed ± 0 | **fixed**: one-sided difference at a domain edge; otherwise "uncertainty unavailable" |
| A σ entered in °F was silently dropped | **fixed**: converted as a difference (× 5/9) |
| The output σ was not converted for temperature units | **fixed** |
| Kept calculations lost their σ; list inputs came back as NaN after loading a session | **fixed**: saved, reloaded and exported |

## Exports

| Finding | Status |
|---|---|
| Excel charts showed only the first 1200 points of a long curve | **fixed**: a thinned copy of the whole curve is charted |
| Provenance lacked the app version, the column mapping and a file fingerprint | **fixed**: all three, plus the import notes |
| Origin files from two runs with one sample name overwrote each other | **fixed**: unique ids |
| Origin COM threading | **fixed**: the export already ran on a worker thread, but each export started a new one. COM objects belong to the thread that created them, so with "Keep Origin open" a second export reached a session made on a thread that no longer existed. All exports now use one long-lived Origin thread, which is joined when the window closes; a test checks the reuse. Untested against a real Origin installation (none on the build machines). |

## Release

- Version 1.1.0. The Word guide was updated: version, the changed passages, and a
  What's-new section. Its screenshots were retaken from version 1.1.0.
- The Windows installer and portable zip are built by `.github/workflows/windows-build.yml`
  (tests, PyInstaller, self-test of the exe, Inno Setup) and downloadable from each run.

## Still open

- The Origin path has only been exercised in script-package mode; a live run against an installed Origin is still to be done on a Windows machine that has it.
