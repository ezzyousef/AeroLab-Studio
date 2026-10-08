"""Self-validation against values published in the three source papers.

Every case below is a number printed in one of the papers (table, text or figure label).
Running `run_all()` recomputes it from the equation library, so a unit slip anywhere in
`equations.py` shows up immediately — in the test suite and in the app's Validation panel.

Not every reference value is a number printed in a paper, so each case says what its
reference value is (`basis`):

* "paper"       -- the value as printed in the cited table or text;
* "cross-check" -- a textbook or physics value the papers rely on (≈70 nm mean free path);
* "ours"        -- our own recomputation from the paper's inputs, because the paper prints
                   no number or prints one we could not reproduce. `paper_value` then holds
                   the printed number when there is one, so the two can be compared.

Two cases are deliberately marked `expect_match=False`: they document internal
inconsistencies found while reading the papers, and assert our value, not theirs.
"""
from __future__ import annotations

from dataclasses import dataclass

from .equations import get

__all__ = ["Case", "CASES", "BASIS_LABELS", "run_all", "summary"]


@dataclass(frozen=True)
class Case:
    name: str
    equation: str
    inputs: dict[str, float]
    expected: float
    tolerance: float          # relative tolerance
    source: str
    expect_match: bool = True
    comment: str = ""
    basis: str = "paper"              # paper | cross-check | ours
    paper_value: float | None = None  # the printed number when basis == "ours"

    @property
    def printed_value(self) -> float | None:
        """The number the paper prints, if it prints one."""
        return self.expected if self.basis == "paper" else self.paper_value


BASIS_LABELS = {"paper": "value printed in the paper", "cross-check": "physics / textbook value",
                "ours": "our recomputation (no matching printed value)"}


CASES: tuple[Case, ...] = (
    # ---------------------------------------------------------------- Paper 1, Table 1
    Case("Porosity, T100-S100", "porosity_from_density", {"rho_b": 0.211, "rho_s": 1.058}, 80.057, 1e-3,
         "Omranpour et al. (2024a), Table 1"),
    Case("Pore volume, T100-S100", "pore_volume", {"rho_b": 0.211, "rho_s": 1.058}, 3.79, 2e-3,
         "Omranpour et al. (2024a), Table 1"),
    Case("Pore diameter, T100-S100", "pore_diameter", {"V_p": 3.79, "S": 350.15}, 43.34, 5e-3,
         "Omranpour et al. (2024a), Table 1"),
    Case("Porosity, T100-S75", "porosity_from_density", {"rho_b": 0.195, "rho_s": 1.065}, 81.695, 1e-3,
         "Omranpour et al. (2024a), Table 1"),
    Case("Pore diameter, T100-S75", "pore_diameter", {"V_p": 4.19, "S": 273.44}, 61.29, 5e-3,
         "Omranpour et al. (2024a), Table 1"),
    Case("Porosity, T150-S100", "porosity_from_density", {"rho_b": 0.263, "rho_s": 1.068}, 75.384, 1e-3,
         "Omranpour et al. (2024a), Table 1"),
    Case("Pore diameter, T150-S75", "pore_diameter", {"V_p": 3.05, "S": 210.4}, 58.07, 5e-3,
         "Omranpour et al. (2024a), Table 1"),

    # ---------------------------------------------------------------- Paper 1, fatigue
    Case("Transition life, T150-S75", "transition_life",
         {"eps_f": 0.34, "E": 18.0, "sigma_f": 7.21, "b": -0.063, "c": -0.14}, 0.12, 0.15,
         "Omranpour et al. (2024a), Table 3 + §3.4", basis="ours",
         comment="Paper reports 'no transition life observed'; our value is far below one reversal, which agrees."),
    Case("SWT amplitude at R = 0", "swt_amplitude", {"sigma_a": 5.13, "sigma_max": 10.26}, 7.255, 1e-3,
         "Omranpour et al. (2024a), Eq. 6 applied to T150-S75 UTS", basis="ours"),

    # ---------------------------------------------------------------- Paper 3, Table 1
    Case("Porosity, NFT-1", "porosity_from_density", {"rho_b": 0.15685, "rho_s": 1.11626}, 85.95, 1e-3,
         "Omranpour et al. (2025), Table 1"),
    Case("Pore volume, NFT-1", "pore_volume", {"rho_b": 0.15685, "rho_s": 1.11626}, 5.48, 2e-3,
         "Omranpour et al. (2025), Table 1"),
    Case("Pore diameter, NFT-1", "pore_diameter", {"V_p": 5.48, "S": 131.0}, 167.32, 5e-3,
         "Omranpour et al. (2025), Table 1"),
    Case("Porosity, NFT-30", "porosity_from_density", {"rho_b": 0.13199, "rho_s": 1.11626}, 88.18, 1e-3,
         "Omranpour et al. (2025), Table 1"),
    Case("Pore diameter, NFT-30", "pore_diameter", {"V_p": 6.68, "S": 51.0}, 523.97, 5e-3,
         "Omranpour et al. (2025), Table 1"),

    # ---------------------------------------------------------------- physics cross-checks
    Case("Mean free path of air, 25 °C, 1 atm", "mean_free_path", {"T": 25.0, "d": 0.364, "p": 101325.0}, 70.0, 0.03,
         "Kinetic theory — the ≈70 nm used throughout the papers", basis="cross-check"),
    Case("Gas conduction in 30 nm pores", "gas_conductivity_knudsen",
         {"k_gas0": 26.0, "porosity": 100.0, "D": 30.0, "beta": 1.63, "l_mfp": 70.0}, 3.0, 0.1,
         "Knudsen model — matches the ≈3 mW/(m·K) quoted for aerogel mesopores", basis="cross-check"),
    Case("Radiation growth 25 → 300 °C", "radiation_temperature_ratio", {"T1": 25.0, "T2": 300.0}, 7.1, 0.02,
         "Rosseland T³ scaling (used in Proposal B)", basis="cross-check"),
    Case("Gel content, 7 % TEPI", "gel_content", {"W_gel": 82.0, "W_0": 100.0}, 82.0, 1e-9,
         "Omranpour et al. (2025), §3.1 (>80 % target)", basis="ours"),
    Case("Elastic recovery ratio, TS-C12 cycle 1", "elastic_recovery", {"eps_max": 100.0, "PS": 5.3}, 94.7, 1e-3,
         "Omranpour et al. (2024b), Table 5"),
    Case("Shape recovery, 90 % compression", "shape_recovery", {"d2": 4.9, "d1": 5.0}, 98.0, 1e-9,
         "Omranpour et al. (2024b), §3.7"),
    Case("SAXS d-spacing of neat TPU", "saxs_q_to_d", {"q": 0.53}, 11.9, 5e-3,
         "Omranpour et al. (2024a), §3.3"),
    Case("SAXS d-spacing after grafting", "saxs_q_to_d", {"q": 0.51}, 12.3, 5e-3,
         "Omranpour et al. (2024a), §3.3"),
    Case("Smallest resolvable d-spacing", "saxs_q_to_d", {"q": 0.08}, 78.54, 5e-3,
         "Omranpour et al. (2024a), §3.3"),
    Case("R-value of a 5 mm mat at k = 29", "r_value", {"t": 5.0, "k": 29.0}, 0.1724, 1e-3,
         "Omranpour et al. (2024b), Eq. 5", basis="ours"),

    # ---------------------------------------------------------------- documented discrepancies
    Case("Effusivity of NFT-4 from k and α", "effusivity_from_k_alpha", {"k": 27.7, "alpha": 0.196}, 62.57, 1e-3,
         "Recomputed from Omranpour et al. (2025), Fig. 6d–e", expect_match=False,
         basis="ours", paper_value=38.2,
         comment="Fig. 6e plots 38.2 W·s^0.5/(m²·K). Eq. 10 with the plotted k and α gives ≈62.6 — worth asking the "
                 "authors how e was obtained."),
    Case("Draw ratio of the final spinning step", "draw_ratio",
         {"V_takeup": 1.0, "Q": 2.0, "d_nozzle": 159.0}, 0.595, 0.02,
         "Computed from Omranpour et al. (2025), §2.4", expect_match=False, basis="ours",
         comment="Take-up (1 m/min) is below the mean nozzle exit speed (≈1.7 m/min), so there is little draw-down; "
                 "the sub-100 µm diameter comes mostly from solvent loss and shrinkage."),
)


@dataclass
class Result:
    case: Case
    value: float
    ok: bool
    rel_error: float


def run_all() -> list[Result]:
    """Recompute every reference case. `ok` means the case behaved as documented."""
    out: list[Result] = []
    for case in CASES:
        value = float(get(case.equation).compute(**case.inputs))
        denom = abs(case.expected) if case.expected else 1.0
        rel = abs(value - case.expected) / denom
        out.append(Result(case, value, rel <= case.tolerance, rel))
    return out


def summary() -> dict[str, int]:
    results = run_all()
    agree = sum(1 for r in results if r.ok and r.case.expect_match)
    printed = sum(1 for r in results if r.ok and r.case.expect_match and r.case.basis == "paper")
    documented = sum(1 for r in results if r.ok and not r.case.expect_match)
    failed = sum(1 for r in results if not r.ok)
    n_printed = sum(1 for r in results if r.case.basis == "paper")
    return {"total": len(results), "reproduced": agree, "reproduced_printed": printed,
            "printed_total": n_printed,
            "documented_discrepancies": documented, "failed": failed}
