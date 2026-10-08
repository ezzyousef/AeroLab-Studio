# Changelog

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
