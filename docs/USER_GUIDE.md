# AeroLab Studio — user guide

---

## 1. The idea

Everything in the three source papers is either *an equation* or *a measurement*.

- An **equation** takes a few numbers and returns one. Porosity from two densities, the
  Knudsen correction, the SWT parameter. You work these by hand, on the **Calculator** page.
- A **measurement** takes columns of instrument data and returns many numbers plus graphs.
  A tensile pull gives a modulus, a UTS, an elongation, a toughness, and a stress–strain
  curve. These live on the **Data** and **Measurements** pages.

The application is built around that split. Both halves feed the same exports.

---

## 2. Getting data in

### Data → Import files, or drag files onto the drop zone

Understood formats: `.csv`, `.tsv`, `.txt`, `.dat`, `.asc`, `.prn`, `.xlsx`, `.xlsm`,
`.xls`, `.json`, `.npz`. Dropping a *folder* imports every readable file in it.

Real instrument exports are messy, and the importer expects that:

| What the file does | What happens |
|---|---|
| Twenty lines of instrument metadata before the header | Detected and skipped; kept in the preview as "header lines skipped" |
| Units on a second header row (Origin's own layout) | Read as units, not as data |
| `Stress (MPa)` in one header cell | Split into a name and a unit |
| `k (mW/(m·K))` — nested brackets | Split correctly |
| `1,234` meaning 1.234 (European locale) | Detected by counting patterns across the file |
| Semicolons, tabs or runs of spaces as separators | Sniffed |
| A multi-sheet workbook | One dataset per sheet that holds numbers |
| A text column such as a sample name | Kept as labels, not forced to NaN |
| A column in kPa, K, °F, mm/mm, reversals … | Converted to the unit the measurement needs; noted in the status bar and the Excel provenance |
| A column of the wrong kind (force in N mapped to stress) | Refused with a message — map the right column or convert it first |
| An old binary `.xls` workbook | Refused with a message: save it as `.xlsx` or `.csv` |

### Check before you commit

Selecting a dataset shows a preview, and beneath it the measurement the app guessed and
the column mapping it intends to use. The pill on the right says whether every required
column was matched. **Nothing is analysed until you press a button**, and every guess is a
dropdown you can change. A column that no header named — filled in only because it was the
next unused one — is marked *guessed from column order, check*, and the pill turns amber.

### Analyse

- **Analyse this dataset** runs the measurement shown.
- **Analyse all imported** guesses for every dataset and runs only those whose measurement
  and columns are clearly named; the rest are listed for you to map by hand.

---

## 3. Measurements

One row per analysed dataset. Three tabs:

- **Results** — every computed quantity with its unit and, where it matters, a note saying
  how it was obtained ("linear baseline between the peak limits").
- **Graph** — the graphs that measurement defines, with a results box placed wherever the
  data leaves room. **Save image…** writes PNG, PDF, SVG or TIFF.
- **Settings** — the analyser's knobs, showing the values the run actually used. Change the
  BET window, the DSC heating rate, the offset-yield strain, then **Re-run with these
  settings**. Until you re-run, an amber note says the results still use the old settings.
  The original data is untouched and `Ctrl+Z` puts the previous result back.

### Notes on the analyses

- **Stress–strain.** The modulus window is the most linear stretch among the steepest
  ones, and must span at least 0.5 % strain. Elongation at break is the last point before
  stress drops below 10 % of the UTS. Set the offset-yield strain to 0 for elastomers and
  foams, where a 0.2 % offset yield has no meaning.
- **S–N and strain–life.** Following ASTM E739, log life is regressed on log stress (or
  strain), because the scatter is in life; the fit is then inverted to the usual Basquin /
  Coffin–Manson form. Exponents carry standard errors and 95 % intervals; the transition
  life has a bootstrap interval. Graphs are plotted against reversals 2N.
- **DSC.** By default endotherms point down (exo up). Tick *Endotherms point up* if your
  instrument exports exo down. For data in mW, enter the sample mass. A transition that
  cannot be found is reported as NaN, not 0.
- **BET.** Only the adsorption branch is used. The fit is checked against the Rouquerol
  criteria and the problems are listed in the note; *Choose BET range automatically* picks
  the widest window that passes. A negative C (typical of microporous, Type I isotherms)
  is refused rather than reported.
- **TGA.** *Dry basis at* renormalises the mass at a chosen temperature so that adsorbed
  water is not counted as decomposition.

### What each measurement reports

| Measurement | Needs | Gives |
|---|---|---|
| Tensile stress–strain | strain %, stress MPa | E, UTS, strain at UTS, elongation at break, toughness, offset yield, resilience |
| Cyclic loading–unloading | strain %, stress MPa | cycles found, permanent set, ER/ε<sub>max</sub>, hysteresis energy, stress softening, ratcheting |
| S–N (Basquin) | N<sub>f</sub>, stress amplitude | σ′<sub>f</sub>, b, R², predicted life |
| Strain–life | N<sub>f</sub>, elastic and plastic amplitudes | b, c, ε′<sub>f</sub>, σ′<sub>f</sub>, transition life |
| Density scaling | density, modulus | scaling exponent with its confidence interval, against Gibson–Ashby |
| TGA | temperature, weight % | T at each loss threshold, onset, residue, DTG peaks |
| DSC | temperature, heat flow | every transition with its own baseline and enthalpy, plus a T<sub>g</sub> estimate |
| Thermal property set | k, ρ, c<sub>p</sub>, (thickness) | diffusivity, effusivity, volumetric heat capacity, R-value, clo |
| N₂ sorption / BET | p/p₀, adsorbed volume | BET area, V<sub>m</sub>, C, total pore volume, mean pore diameter, fit R² |
| Flow curve | shear rate, shear stress | τ<sub>y</sub>, K, n, R², apparent viscosity at 1 s⁻¹ |
| Amplitude sweep | stress, G′, G″ | plateau G′, flow point, modulus at crossover, tan δ |

---

## 4. The Calculator

Every equation, searchable. Pick one and it shows the formula, its source, and an input
for each variable.

- **Units.** Each input has its own unit selector. Type 211 kg/m³ where the equation wants
  g/cm³ and the conversion happens on the way in. The result has a unit selector too.
- **Uncertainty.** The narrow `±` box beside an input is optional. Fill in one or more and
  the result carries a propagated uncertainty: first-order (linearised) propagation with
  numerical derivatives, treating the inputs as independent. It is reliable when σ is small
  enough that the equation is close to linear over ±σ; for large σ or correlated inputs it
  is only an estimate. Where the derivative cannot be evaluated the result says so instead
  of showing ± 0. Uncertainties are kept with **Keep result** and exported.
- **Lists.** A couple of equations (the rule of mixtures) take several values; type them
  comma-separated.
- **Keep result** adds the evaluation to the session so it reaches the Excel export.

---

## 5. Plots

Overlays several runs of the same measurement on one pair of axes — four fibre grades on
one stress–strain plot, the way the papers show them.

Tick the runs to include, choose the graph, and optionally hide the fits. Colours and
symbols are assigned so that neighbouring series never share a shape, and a fit always
takes the colour of the data it belongs to.

---

## 6. Exporting

### Excel

One workbook containing:

- **Summary** — every result of every run, filterable.
- **Calculations** — the equations you kept on the Calculator page.
- **Validation** — the library recomputing the papers' numbers.
- **One sheet per dataset** — results, the settings used, then the raw and derived curves.
- **Charts** — native Excel charts, editable like any other chart.
- **Provenance** — versions, source files, settings, timestamp. Enough to retrace a number.

Measurements that produce one row per sample (the thermal property set) are collapsed into
a single sheet with samples down the rows.

### OriginLab

With Origin installed, **Export to Origin** builds, for each dataset:

- a workbook whose columns carry proper **Long Name**, **Units** and **Comments**, with X
  columns designated so plots pair up correctly;
- every graph the measurement defines, with the publication palette, filled/open symbol
  alternation, dashed fits in their parent's colour, log axes where appropriate, and a
  legend drawn from the column comments;
- a saved `.opju` project, and a PNG of each graph.

Origin takes ten to twenty seconds to start. The export runs on a worker thread, so the
window stays responsive, and Origin is closed cleanly afterwards unless you ask otherwise.

**No Origin on this machine?** Use **Write LabTalk package**. You get Origin-ready CSVs
(Long Name / Units / Comments in the first three rows) plus `AeroLab_build.ogs`. Copy the
folder to a machine with Origin, run the script, and the whole project is rebuilt with the
same styling.

### Figures

A folder of PNG, PDF, SVG, TIFF or EPS at single-column (85 mm), double-column (175 mm),
square or presentation size, at 110, 300 or 600 dpi.

---

## 7. Validation

The trust feature. Twenty-six cases recompute a number printed in one of the papers.

- **reproduced** — our equation returns the published value within tolerance.
- **documented** — we could not reproduce it, and the comment says why. There are two, and
  they are described in the README. They are not bugs and not fudges; they are recorded
  disagreements with the source.
- **FAILED** — should never appear. If it does, the equation library has a real error.

---

## 8. Sessions, undo, shortcuts

**File → Save session** writes a `.aerolab` file holding every result and curve (not the
raw imports, which stay where they are). Reopening restores the analyses.

**Undo and redo** cover importing, analysing, re-running with new settings, removing and
clearing. The buttons sit at the top of the navigation rail and their tooltips name the
action that will be undone. Fifty steps are kept.

| Shortcut | Action |
|---|---|
| `Ctrl+K` or `Ctrl+P` | Command palette — every action, searchable |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `Ctrl+1`…`Ctrl+9` | Jump to a page |
| `Ctrl+O` | Import data |
| `Ctrl+D` | Load the demo datasets |
| `Ctrl+S` | Save session |
| `Ctrl+E` | Export to Excel |
| `Ctrl+R` | Export to Origin |
| `Ctrl+T` | Toggle light / dark |

---

## 9. If something goes wrong

**"no columns matched."** The headers do not look like anything the measurement expects.
Set the mapping by hand in the dropdowns — matching is a convenience, not a requirement.

**A number looks wrong.** Open the Graph tab. Most surprises are visible: a modulus fitted
over the wrong window, a DSC peak whose limits ran into its neighbour. The Settings tab
usually has the knob that fixes it.

**Origin export failed.** Check Settings → Environment. If Origin is listed as unavailable,
use the LabTalk package. If Origin is available but the export failed, tick "Show Origin
while it works" and run it again to watch where it stops.

**The DSC glass transition looks wrong.** It is an estimate, and it says so. The heuristic
looks for the steepest baseline step below the first melting or crystallisation peak. A
T<sub>g</sub> buried under a large melt cannot be found this way — read it off the graph.

---

## 10. About

The **About** page (also Help → About) carries the author and laboratory details, what the
program contains, the three papers it implements, and the versions of everything it is
running on — useful when reporting a problem.

---

Made by **Ezzeldien Yousef** · ezz.yousef@mail.utoronto.ca
MPML — Microcellular Plastics Manufacturing Laboratory
Department of Mechanical & Industrial Engineering, University of Toronto
