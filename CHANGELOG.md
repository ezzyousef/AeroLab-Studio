# Changelog

## 1.3.0 (upgrade 06)

**Scientific correctness**
- Every one of the 59 equations now has an independent first-principles oracle test, and 16 of them are also checked against values worked by hand. See `docs/EQUATION_REGRESSION_REPORT.md`.
- Fixed: a BET isotherm listed from high to low pressure was cut down to one point and refused.
- Fixed: the crossover modulus was interpolated linearly, although the crossing is found in log–log space (0.33 % high on a power-law sweep).
- Fixed: six quantities that carry real units were declared dimensionless (tex, specific strength, bending rigidity, diffusion coefficient, Herschel–Bulkley K, the crosslink K), so the Calculator offered "%" for them and scaled them by 0.01. They now have proper dimensions. Every dimension has an SI signature, and wt%/phr were removed from the g/L table.
- Fixed importer cases: UTF-16 and UTF-32 files, binary files, files over 256 MB, ragged rows (now reported row by row instead of being truncated silently), empty trailing columns, and an amplitude-sweep x in % or rad/s (it was refused).
- Fatigue fit lines stop at the tested lives. A predicted life outside them is flagged as an extrapolation.

**New**
- Uncertainty: an optional correlation matrix (it must be positive semi-definite) and a Monte Carlo cross-check with a histogram that compares the linear ±1σ with the Monte Carlo 95 % interval. Kept calculations record the method used.
- Workspace: samples (composition, spinning and process parameters, densities with derived porosity, geometry, thermal history, replicates), experiments (instrument, calibration date, operator, linked runs), attachments recorded with SHA-256, and a chain-of-custody log. Session schema v2, with migration of v1 files. Portable `.aerolabz` archives that are verified on import.
- Mechanics studio: modulus-window sensitivity, energy per cycle, Basquin vs Wöhler compared by AIC with bootstrap intervals, bootstrap intervals for the strain–life constants, relaxation and creep models (new measurements, with demo files clearly marked SYNTHETIC), and images linked through the Workspace.
- Materials studio: TGA decomposition steps, a DSC event table (crystallinity only from a ΔH°m you enter), k versus density (new measurement), BET vs density porosity summary, end of the LVER, and QC flags that include missing or stale calibration.
- Explorer: batch statistics (Welch, ANOVA), density-normalised comparison, response surface, elasticities, Buckingham-π groups, DOE suggestions (results left blank), a publishable HTML/Markdown report with provenance, and read-back verification of Excel exports.
- Notebook, figure layout templates with panels labelled (a), (b) and so on, a streaming data preview for long files, an overview of how every imported file maps, task-grouped navigation that scrolls, fractional high-DPI scaling, and the `.aerolabz` file association.

**Tests**: 121 → 374. The test suite no longer touches the user's real settings file, and it deletes windows between tests (230 s → about 130 s on an idle machine).

## 1.2.1

- **Analyse all and figure export no longer freeze the window:** a progress dialog shows each dataset/figure and has Cancel.
- Analyse all stays on the Data page (on the first file that needs mapping) when some files were skipped, instead of jumping to Measure.
- Figure export reports all failures in one message instead of one toast each.

## 1.2.0

- **Figures in the lab's house style (Figure Studio's):** the "Review" palette and Figure Studio's Light/Dark colours, DejaVu Sans with bold axis titles and tick labels, an open frame, outward ticks, a horizontal grid only and a frameless legend — on screen and in every PNG/SVG/PDF export.
- **Accessibility (WCAG 2.2 AA), from a UX/accessibility review:**
  - Visible keyboard focus on buttons, inputs, check boxes, radio buttons and table items.
  - Input and check-box outlines that meet 3:1 contrast.
  - Accent-coloured text (selected tabs, link-style buttons) at 4.5:1 or better in both themes.
  - Readable section headings in the side bar.
  - Labels tied to their inputs (Alt+letter focuses the field; screen readers announce it).
- **House accent colour:** the house blue #2E6FD9 (a lighter tint with dark text in the dark theme), with a separate text tint so it passes 4.5:1 everywhere. Settings saved with the old default palette move to "review" once; a palette you chose stays.
- **Invalid settings are no longer ignored:** a value that is not a number (e.g. "0,2x") is reported and selected instead of silently becoming "not set".
- **Import drop zone works from the keyboard:** Tab to it and press Enter or Space.
- **Ctrl+Z works again** (a duplicate shortcut made Undo ambiguous, so Qt ignored it); Redo is Ctrl+Shift+Z or Ctrl+Y.
- **Ctrl+1 … Ctrl+9** page shortcuts are shown in the View menu.
- **Keyboard:** focus ring on the navigation buttons and checked boxes; Tab leaves tables; the plot toolbar is reachable; every caption is tied to its input, including the calculator's value, unit and ± fields.
- **Validation page** status colours follow the dark theme; error messages stay on screen for 15 s (warnings 9 s).

## 1.1.0

See `docs/REVIEW_LOG.md` for every review finding and what was done.

- **Import:**
  - units are converted to what each analysis needs, and a column of the wrong kind is refused;
  - columns picked only by position are flagged;
  - "Analyse all" skips files it cannot identify;
  - readers handle uncommented preambles, ambiguous decimal commas, chartsheets and `.xls`.
- **Fatigue:** fits follow ASTM E739, with standard errors and 95 % intervals, plotted against 2N.
- **Stress–strain:** break detection, a more robust modulus window, and an optional offset yield.
- **DSC:**
  - the direction option is now "Endotherms point up" (old sessions are translated);
  - per-mass normalisation;
  - robust limits for broad peaks.
- **BET and TGA:** BET uses the adsorption branch only, with Rouquerol checks, an automatic range and standard errors. TGA merges repeated temperatures and has a dry-basis option.
- **Herschel–Bulkley:** relative weighting.
- **Power-law fits:** t-based confidence intervals.
- **Graphs:** fitted and integrated ranges are shaded.
- **Validation:** each case states its basis (printed in the paper, physics check, or recomputation).
- **Calculator:** first-order uncertainty, with NaN instead of 0 when it fails. A temperature σ is converted correctly. Uncertainties are saved and exported.
- **Exports:** long curves are charted whole; provenance records the version, the column mapping and the SHA-256 of each source file; Origin ids are unique.
- **Interface:** pages scroll on small screens, the Settings tab shows the values actually used, and the dark theme meets WCAG AA for text.
- **Windows build** on GitHub Actions.
