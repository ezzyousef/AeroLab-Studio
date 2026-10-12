# Changelog

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
