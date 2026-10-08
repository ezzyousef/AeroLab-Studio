# AeroLab Studio

A desktop application for aerogel-fibre research: every equation and measurement from
three papers on thermoplastic-polyurethane aerogels, applied by hand or automatically,
with publication figures exported straight into OriginLab and a formatted Excel workbook.

Built from:

- Omranpour *et al.* (2024a) — TPU aerogels: structure, fatigue and strain–life
- Omranpour *et al.* (2024b) — TPU/silica composite aerogels: thermal and cyclic behaviour
- Omranpour *et al.* (2025) — nanofibrous aerogel fibres: spinning, structure, properties

**User guide:** `AeroLab_Studio_User_Guide.docx` in this folder — step by step, with screenshots
(`docs/USER_GUIDE.md` is the same material as plain text).

---

## What it does

| | |
|---|---|
| **59 equations** | The relations used in the three papers, with unit conversion on every input and first-order uncertainty propagation (independent inputs). |
| **11 measurements** | Stress–strain, cyclic loading, S–N, strain–life, density scaling, TGA, DSC, thermal properties, BET, Herschel–Bulkley, amplitude sweep. |
| **Automatic import** | CSV, TSV, TXT, DAT, Excel (.xlsx), JSON, NumPy archives. Instrument preambles, unit rows, European decimals and multi-sheet workbooks are handled; columns are matched to the measurement by name and converted to the unit the analysis needs. Columns that had to be guessed are flagged. |
| **Origin export** | Styled workbooks (Long Name / Units / Comments) and graphs with publication colours and symbols, saved as a `.opju` project with PNG exports. No Origin on the machine? It writes a LabTalk package that rebuilds the same project elsewhere. |
| **Excel export** | Summary, one sheet per dataset with its curves, native Excel charts, the validation table, and a provenance sheet recording versions, files and settings. |
| **Self-validation** | 26 reference cases: 17 recompute numbers printed in the papers, 7 are physics or recomputation checks, and 2 record disagreements *with the papers*, with the reasoning stated. Each case says which kind it is. These check the equation library, not the curve analysers — those are covered by the test suite on synthetic data. |

---

## Install and run

### The built application (no Python needed)

Run `AeroLabStudio-Setup.exe`, or unzip the portable folder and run `AeroLabStudio.exe`.

### From source

```bash
pip install -r requirements.txt
python main.py
```

Python 3.11 or newer. Tested on Python 3.14 with PySide6 6.11.

OriginLab support is optional. With Origin installed and `pip install originpro pywin32`,
the app drives it directly; without, it writes a script package instead.

---

## A five-minute tour

1. **Data → Load demo data.** Eleven datasets from the papers appear, deliberately messy:
   instrument preambles, a units row, European decimals.
2. Pick one. The preview shows what was parsed; the measurement is guessed from the
   headers and the file name, and each column is mapped. Change anything you disagree with.
3. **Analyse this dataset.** The results, the graph and the settings appear under
   Measurements. Change a setting and re-run — it is free to try, and `Ctrl+Z` undoes it.
4. **Plots** overlays several runs on one pair of axes.
5. **Export** writes the Excel workbook, or sends everything to Origin.
6. **Validation** shows the equation library recomputing the papers' own numbers, and
   says for each case whether the reference is a printed value or a cross-check.

See `docs/REVIEW_LOG.md` for the independent review of this version and what changed.

`Ctrl+K` opens a command palette with every action in the app.

---

## Layout

```
aerolab/
  core/
    units.py          ~28 dimensions, exact conversion factors
    equations.py      59 equations, each with inputs, units and a reference
    curves.py         the analysers: fits, peaks, integrals
    measurements.py   what each experiment needs, and what it plots
    validation.py     26 reference cases (printed values, physics checks, discrepancies)
  io/
    readers.py        delimiter sniffing, unit rows, Excel, JSON, NPZ
    excel.py          the formatted workbook with native charts
    origin.py         live Origin automation, and the LabTalk fallback
  viz/
    style.py          the palette and symbol set, shared with Origin
    figures.py        matplotlib rendering
  ui/
    app.py            main window, navigation, command palette
    state.py          the session, with undo/redo
    widgets.py        cards, tiles, toasts, plot canvas, formula rendering
    pages/            one file per page
  resources/samples/  the eleven demo datasets
tests/                pytest suite
docs/USER_GUIDE.md    the longer guide
```

---

## Testing

```bash
pip install pytest
pytest tests -v
```

The suite checks the equation library against the papers, the analysers against synthetic
data with known answers, the importer against deliberately awkward files, the Excel and
Origin writers, and a headless smoke test of the interface.

---

## Building the application

```bash
pip install pyinstaller
python build_assets/make_icon.py          # draws the icon and version resource
pyinstaller AeroLabStudio.spec --noconfirm
```

`dist/AeroLabStudio/` is a self-contained folder. To build the installer, install
[Inno Setup](https://jrsoftware.org/isinfo.php) and compile `installer/AeroLabStudio.iss`.

---

## Two things the papers and this program disagree about

Both are shown on the Validation page rather than hidden:

1. **Effusivity of NFT-4.** Figure 6e plots 38.2 W·s^0.5/(m²·K). Equation 10 applied to the
   *k* and *α* plotted in the same figure gives ≈62.6. Worth asking the authors.
2. **Draw ratio of the final spinning step.** The stated take-up speed is below the mean
   nozzle exit speed, so there is little draw-down; the sub-100 µm fibre diameter comes
   mostly from solvent loss and shrinkage.

---

## Author

**Ezzeldien Yousef** — ezz.yousef@mail.utoronto.ca
MPML, Microcellular Plastics Manufacturing Laboratory
Department of Mechanical & Industrial Engineering, University of Toronto

The same details are on the application's **About** page, with a copy-to-clipboard button.
