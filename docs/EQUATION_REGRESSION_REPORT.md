# Equation regression report

What the equation library and the curve analysers are checked against, and what they are
not. Branch `upgrade/06-aerolab`, 2026-11-15.

Run:

```
py -3 -m pytest -q -p no:cacheprovider tests/test_equation_oracles.py tests/test_curve_oracles.py tests/test_paper_discrepancies.py tests/test_units_dimensions.py tests/test_uncertainty.py
```

Three kinds of check are used. Each row says which one it is.

- **Printed**: the library reproduces a number printed in one of the three source papers
  (`aerolab/core/validation.py`, 17 cases, run by `test_core.py` and shown on the Validation page).
- **Recovery**: synthetic data is built from a known truth (an exact BET isotherm, a
  Gaussian DSC peak of known area, an analytic hysteresis loop). The analyser has to return
  the parameter the data was built from. The expected value is derived on paper, never
  by running the code under test.
- **Consistency**: the code applies the stated formula with the stated units. The expected
  value is worked out again in the test, in SI units and written differently from the code
  (for example the papers' form (1/ρb − 1/ρs)/(1/ρb) instead of the code's 1 − ρb/ρs). It
  catches unit slips, wrong constants and swapped arguments. It cannot catch a formula
  that is wrong in the paper.

## 1. Equation library: 59 of 59 equations (consistency)

`tests/test_equation_oracles.py`, 84 tests. Every registered equation has an independent
oracle. `test_every_equation_has_an_independent_oracle` fails if an equation is added
without one. Sixteen results are also checked against values worked by hand:

| Equation | Inputs | Hand value | App |
|---|---|---|---|
| Pore diameter 4V/S | V = 3.79 cm³/g, S = 350.15 m²/g | 43.296 nm | 43.296 nm |
| Linear density (tex) | D = 90 µm, ρ = 0.151 g/cm³ | 0.9606 tex | 0.9606 tex |
| Mean free path of air | 25 °C, 1 atm, d = 0.364 nm | 69.0 nm | 69.0 nm |
| Rosseland k_rad | n = 1, 25 °C, e* = 0.05 m²/g, ρ = 0.151 g/cm³ | 1.0616 mW/(m·K) | 1.0616 |
| k_rad ratio | 25 → 300 °C | 7.104 | 7.104 |
| Diffusivity k/(ρ·cp) | 27.7 mW/(m·K), 0.1508 g/cm³, 1000 J/(kg·K) | 0.18369 mm²/s | 0.18369 |
| Effusivity √(kρcp) | same | 64.631 W·s^0.5/(m²·K) | 64.631 |
| Effusivity k/√α | k = 27.7, α = 0.196 mm²/s | 62.568 | 62.568 |
| Engineering stress | 0.074 N on a 90 µm fibre | 11.632 MPa | 11.632 |
| Halpin–Kardos | Em = 12, Ef = 10⁵ MPa, φ = 0.0148, l/d = 50 | 29.986 MPa | 29.986 |
| Nozzle exit velocity | 2 mL/h through 159 µm | 1.6788 m/min | 1.6788 |
| Draw ratio | 1 m/min take-up, same nozzle | 0.59567 | 0.59567 |
| Phase angle | G′ = 30 kPa, G″ = 5 kPa | 9.4623° | 9.4623° |
| Scattering vector | λ = 1.54 Å, θ = 0.5° | 0.71207 nm⁻¹ | 0.71207 |
| Bragg spacing | Cu Kα, 2θ = 22° | 0.40370 nm | 0.40370 |
| Scherrer size | K = 0.9, β = 0.5°, 2θ = 22° | 16.186 nm | 16.186 |

Limits and identities (consistency): porosity is 0 at ρb = ρs and 100 % at ρb = 0.
ε = Vp·ρb holds for every density pair. Halpin–Kardos returns Em at φ = 0 or Ef = Em, and
the Voigt bound at l/d → ∞. The two effusivity forms agree when α = k/(ρcp). The draw
ratio is take-up speed ÷ exit speed. The transition life is where the elastic and plastic
branches are equal. The k-model breakdown sums to the registered equation.

## 2. Curve analysers (recovery)

`tests/test_curve_oracles.py`, 17 tests. Anything that interpolates, differentiates or
integrates along x is run with the points in both orders, because `np.interp` and
`np.gradient` give silently wrong answers on falling x.

| Analyser | Synthetic truth | Expected | Result |
|---|---|---|---|
| BET | exact isotherm, vm = 80 cm³/g, C = 150, **both orders** | S = vm/22414·Nₐ·0.162 nm² = 348.2 m²/g, C = 150 | equal (1e-6). **Falling order used to be refused: fixed** |
| Gurvich volume | exact BET isotherm with 0.99 as a grid point | V(0.99)·28.0134/0.808/22414 | within 0.2 % |
| DSC enthalpy | Gaussian endotherm, A·w·√π / rate, **both orders** | 0.8·6·√π/(20/60) = 25.5 J/g | within 2 % |
| DSC in mW + mass | the same curve in mW with a 5 mg mass | J/g | within 2 % |
| TGA thresholds | logistic step, t0 = 400 °C, s = 12 °C, **both orders** | T5 = t0 − s·ln(…), T30 = t0, residue 40 % | within 0.1 °C |
| Hysteresis | load σ = Eε, unload σ = Eε²/εmax | ΔW = Eε²/6, dissipation ratio 1/3 | within 0.1 % |
| Toughness | elastic to 2 % at 100 MPa, then flat at 2 MPa to 50 % | 0.98 MJ/m³ | within 0.01 % |
| Modulus window | linear to 2 %, then curved, **both orders** | 30 MPa | within 1 % |
| Crossover | G′ = 2·10⁴x^−0.5, G″ = 50x^0.4, **both orders** | x* = 400^(1/0.9), G* = 2·10⁴x*^−0.5 | equal (1e-9). **The modulus was 0.33 % high: fixed** |
| Herschel–Bulkley | τ = 120 + 8γ̇^0.6, falling order | τy, n | equal (1e-4) |
| Basquin | exact σa = 7.21(2N)^−0.063 | σ′f, b, N at 0.5σ′f = 0.5·0.5^(1/b) | equal (1e-9) |
| Thermal point | k = 30 mW/(m·K), ρ = 0.12 g/cm³, cp = 1300, t = 4 mm | α, e, ρcp, R, clo from the SI chain | equal (1e-12) |

The older recovery tests in `tests/test_curves.py` (modulus with a toe region, cyclic
permanent set under a noise floor, strain–life transition, two melts on a Tg step, the
ASTM E739 fatigue fits, scaling exponent) still run unchanged.

## 3. The two documented disagreements with the papers

`tests/test_paper_discrepancies.py`. Both are kept as the app's own recomputation, with
the printed number beside it. Neither is changed to match the paper.

1. **Effusivity of NFT-4.** Eq. 10 with the k and α plotted in Fig. 6d–e gives
   0.0277/√(0.196·10⁻⁶) = 62.57 W·s^0.5/(m²·K). Fig. 6e prints 38.2. To get 38.2 the
   diffusivity would have to be ≈0.526 mm²/s, which the test also pins.
2. **Draw ratio of the last spinning step.** The exit speed is 1.679 m/min. With a 1 m/min
   take-up the draw ratio is 0.596, which is below 1, so the fibre is not drawn down.

## 4. Unit dimensionality audit

`tests/test_units_dimensions.py`. Six quantities were declared "dimensionless" although
they carry a unit. Because of that the Calculator offered "%" for them, and picking it
silently multiplied the value by 0.01:

| Equation / symbol | Was | Now |
|---|---|---|
| fibre_areal_density / tex | "-" dimensionless | tex (linear_density: tex, dtex, den, g/km) |
| specific_strength / σspec | "-" | MPa·cm³/g (= kN·m/kg; cN/tex) |
| bending_rigidity / EI | "-" | N·m² |
| diffusion_time / D | "-" | m²/s (diffusion_coefficient) |
| herschel_bulkley / K | "-" | Pa·sⁿ (no conversions, since the unit depends on n) |
| density_scaling_crosslinked / K | "-" | MPa (C is a fraction, so K carries E's unit) |

The `concentration` table also listed wt% and phr with a factor of 1 to g/L. Those are
mass ratios, so they are removed. Every dimension now has an SI base-dimension signature
(M, L, T, Θ). The Explorer uses it for dimensional analysis.

## 5. Uncertainty propagation

See section 6 of `docs/UPGRADE_TEST_REPORT.md` and `tests/test_uncertainty.py`. In short,
these are checked:

- the linearised result with a full covariance matrix, against closed forms for a product,
  a ratio and a sum with correlation;
- the exact cancellation of x/x when the correlation is +1;
- refusal of a correlation matrix that is not positive semi-definite;
- a Monte Carlo cross-check that agrees with the linear result for small σ, and that
  shows the bias of the linear result for 1/x when σ is large.

## What this does not cover

- **Real instrument exports.** None were supplied with the repository beyond the 12
  bundled demo files, so every recovery test uses synthetic data. On real, noisy data the
  results still depend on the modulus window, the BET range, the DSC peak limits and the
  TGA dry-basis point. The app shows all of these to the user.
- **Correctness of the papers' own formulas.** Consistency checks prove that the code does
  what the formula says, not that the formula suits a given material. The Knudsen
  gas-conduction term, the Rosseland radiative term and the three-mechanism k-model are
  textbook approximations. The k-model uses still-air values at 25 °C (26 mW/(m·K),
  70 nm) whatever temperature is entered. This is stated in the equation notes.
- **The Glass transition estimate and the DSC peak limits** have recovery tests on clean
  synthetic curves only (`test_curves.py`). Overlapping events on a sloping baseline are
  covered by the two-melt test, and nothing more difficult than that.
- **Fatigue confidence intervals** assume log-normal life scatter (ASTM E739). The
  bootstrap interval of the transition life needs at least 4 specimens and 50 successful
  resamples, otherwise no interval is reported.
- **The literature sources** were not re-read in this round. The 17 printed cases are
  the values transcribed in earlier versions.
