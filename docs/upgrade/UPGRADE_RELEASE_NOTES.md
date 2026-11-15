# AeroLab Studio 1.3.0: release notes

## What changes for you

- **Numbers you may see change**
  - A BET file that lists its points from high to low pressure now analyses. Before, it was refused.
  - The "Modulus at crossover" of an amplitude sweep is now read in log–log space, so values move by a fraction of a percent (0.33 % on a power-law test sweep).
  - Fatigue fit lines now stop at your tested lives. A "Predicted life" outside them now says OUTSIDE.
  - New metrics appear for tensile tests (modulus window sensitivity), cyclic tests (cumulative dissipated energy, dissipation ratio), TGA (decomposition steps and their losses) and amplitude sweeps (end of the linear viscoelastic region).
- **Calculator.** Six quantities now show their real units: tex, MPa·cm³/g, N·m², m²/s, Pa·sⁿ, and MPa for the crosslink constant. Before, choosing "%" for them silently divided the value by 100. Correlations… and Monte Carlo check are new; both are optional.
- **Importing.** UTF-16 files (common from Windows instrument software) now read correctly. A row with more or fewer fields than the table is listed under the preview, and in the new "All files at a glance" table, instead of being cut quietly. Files over 256 MB and binary files are refused with a message.
- **New pages**
  - Workspace: samples, experiments, attachments, chain of custody.
  - Notebook.
  - Mechanics studio, Materials studio and Explorer.
- **New measurements.** Stress relaxation, creep, and thermal conductivity versus density. The relaxation and creep demo files are **synthetic** and say so in their first line.
- **Files**
  - Sessions are saved as schema 2. 1.2 sessions open and are upgraded automatically; a note appears in the status bar. A 1.2 installation cannot open a 1.3 session that uses the new features (it ignores the workspace).
  - File → Save archive writes a `.aerolabz` file: the session plus every attached file, each checked by SHA-256 when it is opened.
- **Reports.** Explorer → Write report creates an HTML and a Markdown report with results, units, assumptions, equations and sources, QC flags, sample records, file hashes and the lineage log.

## Migration notes

- Nothing to do. Old `.aerolab` files are migrated in memory when opened, and are only rewritten when you save.
- Analysis settings saved by older versions still apply (`exo_up` → `endotherm_up`, as before).

## Security notes

- Archive import refuses absolute paths, `..` components, drive letters, members over 512 MB, a total over 2 GB, compression ratios above 200:1, and any attachment whose SHA-256 does not match. It never overwrites a different existing file.
- The HTML report escapes every value taken from your files. It contains no scripts and loads nothing from outside the file.
- The app makes no network connection, as before. The test suite no longer reads or writes your real `~/.aerolab_studio/settings.json`.

## Known limits

- Recovery tests use synthetic curves. No measured reference curves with certified answers were supplied.
- Response surfaces need at least 7 runs at 3 or more levels of each factor. The DOE panel proposes settings only.
- Crystallinity is shown only when you enter ΔH°m; no reference value is assumed for TPU.
- The installer was not rebuilt in this round (see the handoff).
