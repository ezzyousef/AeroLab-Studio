"""The measurement registry — one description per experiment, used by everything else.

A `Measurement` says what columns an experiment needs, what knobs it has, which analyser
turns it into numbers, and which graphs come out of it.  The importer uses it to guess
columns, the plot layer to draw figures, the Origin bridge to build workbooks and graphs,
and the Excel writer to lay out sheets.  Add an experiment here and it appears everywhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from . import curves as C
from .curves import AnalysisResult

__all__ = [
    "Channel", "Option", "Series", "Plot", "Measurement",
    "MEASUREMENTS", "CATEGORIES", "get", "by_category", "match_columns", "search",
]


# ---------------------------------------------------------------------------
# building blocks
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Channel:
    """One column an experiment needs."""
    key: str                      # argument name passed to the analyser
    label: str                    # what the user sees, and the Origin Long Name
    unit: str
    dimension: str
    aliases: tuple[str, ...] = ()  # extra header spellings seen in instrument exports
    required: bool = True
    help: str = ""

    def matches(self, header: str) -> float:
        """0-1 score for how well a file header names this channel."""
        h = _norm(header)
        if not h:
            return 0.0
        names = (self.label, self.key, *self.aliases)
        best = 0.0
        for name in names:
            n = _norm(name)
            if not n:
                continue
            if h == n:
                best = max(best, 1.0)
            elif h.startswith(n) or n.startswith(h):
                best = max(best, 0.85)
            elif n in h or h in n:
                best = max(best, 0.7)
            else:
                shared = set(n.split()) & set(h.split())
                if shared:
                    best = max(best, 0.4 + 0.1 * len(shared))
        if best and _norm(self.unit) and _norm(self.unit) in _norm(header):
            best = min(1.0, best + 0.1)
        return best


@dataclass(frozen=True)
class Option:
    """A analyser setting exposed in the UI."""
    key: str
    label: str
    kind: str                     # float | int | bool | range | choice
    default: Any
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    unit: str = ""


@dataclass(frozen=True)
class Series:
    """One trace on a graph, pulled from `AnalysisResult.curves`."""
    curve: str                    # key in AnalysisResult.curves, or "*" to expand all
    label: str
    style: str = "scatter"        # scatter | line | scatter+line
    role: str = "data"            # data | fit | guide — drives colour and symbol choice


@dataclass(frozen=True)
class Plot:
    id: str
    title: str
    x_label: str
    x_unit: str
    y_label: str
    y_unit: str
    series: tuple[Series, ...]
    xscale: str = "linear"        # linear | log
    yscale: str = "linear"
    note: str = ""

    @property
    def x_axis(self) -> str:
        return f"{self.x_label} ({self.x_unit})" if self.x_unit else self.x_label

    @property
    def y_axis(self) -> str:
        return f"{self.y_label} ({self.y_unit})" if self.y_unit else self.y_label


@dataclass(frozen=True)
class Measurement:
    id: str
    name: str
    category: str
    summary: str
    channels: tuple[Channel, ...]
    plots: tuple[Plot, ...]
    analyser: Callable[..., AnalysisResult]
    options: tuple[Option, ...] = ()
    kind: str = "series"          # series = columns of a curve; table = one row per sample
    reference: str = ""
    sample: str = ""              # bundled demo file name
    tags: tuple[str, ...] = ()

    # -- use -----------------------------------------------------------------
    def required_channels(self) -> tuple[Channel, ...]:
        return tuple(c for c in self.channels if c.required)

    def channel(self, key: str) -> Channel:
        for c in self.channels:
            if c.key == key:
                return c
        raise KeyError(f"{self.id}: no channel {key!r}")

    def defaults(self) -> dict[str, Any]:
        return {o.key: o.default for o in self.options}

    def run(self, data: dict[str, Sequence[float]], **options: Any) -> AnalysisResult:
        """Run the analyser. `data` is keyed by channel key; missing optionals are skipped."""
        missing = [c.key for c in self.required_channels() if c.key not in data or data[c.key] is None]
        if missing:
            raise ValueError(f"{self.name}: missing required column(s): {', '.join(missing)}")
        args = [np.asarray(data[c.key], dtype=float) for c in self.channels
                if c.required or (c.key in data and data[c.key] is not None)]
        kwargs = {**self.defaults(), **{k: v for k, v in options.items() if v is not None}}
        kwargs = {k: v for k, v in kwargs.items() if k in {o.key for o in self.options}}
        result = self.analyser(*args, **kwargs)
        result.meta.setdefault("measurement", self.id)
        return result

    def run_table(self, rows: Sequence[dict[str, float]], **options: Any) -> list[AnalysisResult]:
        """For `kind == 'table'` measurements: one analyser call per row."""
        out = []
        for row in rows:
            args = [float(row[c.key]) for c in self.channels if c.required]
            extra = {c.key: float(row[c.key]) for c in self.channels
                     if not c.required and row.get(c.key) is not None}
            res = self.analyser(*args, **extra, **{k: v for k, v in options.items() if v is not None})
            res.meta.setdefault("measurement", self.id)
            out.append(res)
        return out

    def match_columns(self, headers: Sequence[str]) -> dict[str, int | None]:
        return match_columns(self, headers)


# ---------------------------------------------------------------------------
# header matching
# ---------------------------------------------------------------------------
_PUNCT = re.compile(r"[\[\]\(\)\{\}/·°%^_,;:\-\.\*\+]+")


def _norm(text: str) -> str:
    text = str(text or "").strip().lower()
    text = _PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_columns(measurement: Measurement, headers: Sequence[str]) -> dict[str, int | None]:
    """Best-effort mapping channel key -> column index, using names then position.

    Greedy on the strongest score first so a header like "Stress" cannot steal the slot
    that "Strain" matched better.  Unmatched required channels fall back to file order.
    """
    scores: list[tuple[float, str, int]] = []
    for ch in measurement.channels:
        for i, head in enumerate(headers):
            s = ch.matches(head)
            if s >= 0.4:
                scores.append((s, ch.key, i))
    scores.sort(key=lambda t: (-t[0], t[1]))

    mapping: dict[str, int | None] = {c.key: None for c in measurement.channels}
    used: set[int] = set()
    for _score, key, idx in scores:
        if mapping[key] is None and idx not in used:
            mapping[key] = idx
            used.add(idx)

    free = [i for i in range(len(headers)) if i not in used]
    for ch in measurement.channels:
        if mapping[ch.key] is None and ch.required and free:
            mapping[ch.key] = free.pop(0)
    return mapping


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def _ch(key, label, unit, dim, *aliases, required=True, help="") -> Channel:
    return Channel(key, label, unit, dim, tuple(aliases), required, help)


MEASUREMENTS: tuple[Measurement, ...] = (
    # ------------------------------------------------------------ mechanical
    Measurement(
        id="stress_strain",
        name="Tensile stress–strain",
        category="Mechanical",
        summary="Young's modulus, UTS, elongation at break, toughness and offset yield from a "
                "single monotonic pull.",
        channels=(
            _ch("strain_pct", "Strain", "%", "dimensionless",
                "tensile strain", "strain (%)", "elongation", "displacement", "ε",
                help="Engineering strain in percent."),
            _ch("stress_mpa", "Stress", "MPa", "stress",
                "tensile stress", "stress (MPa)", "engineering stress", "σ", "load"),
        ),
        options=(
            Option("offset_yield", "Offset yield strain", "float", 0.002,
                   "Offset used for the yield point (0.002 = the usual 0.2 % offset).",
                   minimum=0.0, maximum=0.05),
            Option("min_window", "Minimum modulus window", "int", 8,
                   "Fewest points the automatic modulus search may use.", minimum=4, maximum=200),
        ),
        plots=(
            Plot("curve", "Tensile stress–strain", "Strain", "%", "Stress", "MPa",
                 (Series("stress-strain", "Stress–strain", "line", "data"),
                  Series("modulus fit", "Initial modulus fit", "line", "fit")),
                 note="Dashed trace is the window used for E."),
        ),
        analyser=C.analyze_stress_strain,
        reference="Omranpour et al. (2024a), §3.4; (2025), §3.5",
        sample="tensile_NFT-4.csv",
        tags=("tensile", "modulus", "UTS", "toughness"),
    ),
    Measurement(
        id="cyclic_tension",
        name="Cyclic loading–unloading",
        category="Mechanical",
        summary="Permanent set, elastic recovery ratio, hysteresis energy, stress softening and "
                "ratcheting from a multi-cycle test.",
        channels=(
            _ch("strain_pct", "Strain", "%", "dimensionless", "cyclic strain", "elongation", "ε"),
            _ch("stress_mpa", "Stress", "MPa", "stress", "cyclic stress", "σ", "load"),
        ),
        options=(
            Option("zero_stress_fraction", "Zero-stress threshold", "float", 0.02,
                   "Fraction of peak stress treated as “unloaded” when locating permanent set.",
                   minimum=0.001, maximum=0.2),
        ),
        plots=(
            Plot("loops", "Loading–unloading cycles", "Strain", "%", "Stress", "MPa",
                 (Series("*", "Cycle", "line", "data"),),
                 note="One trace per detected cycle; the rightward drift is the permanent set."),
        ),
        analyser=C.analyze_cyclic_tension,
        reference="Omranpour et al. (2024b), Table 5; (2025), Fig. 8",
        sample="cyclic_TS-C12.csv",
        tags=("cyclic", "hysteresis", "recovery", "ratcheting"),
    ),
    Measurement(
        id="sn_curve",
        name="S–N (Basquin) fatigue",
        category="Fatigue",
        summary="Fatigue strength coefficient and exponent from stress amplitude versus life.",
        channels=(
            _ch("cycles", "Cycles to failure", "cycles", "cycles", "Nf", "life", "N"),
            _ch("stress_amplitude", "Stress amplitude", "MPa", "stress", "σa", "amplitude", "sigma_a"),
        ),
        plots=(
            Plot("sn", "S–N curve", "Reversals to failure 2N", "reversals",
                 "Stress amplitude", "MPa",
                 (Series("data", "Measured", "scatter", "data"),
                  Series("fit", "Basquin fit", "line", "fit")),
                 xscale="log", yscale="log"),
        ),
        analyser=C.fit_sn_basquin,
        reference="Omranpour et al. (2024a), Eq. 4 and Table 3",
        sample="fatigue_sn.csv",
        tags=("fatigue", "Basquin", "S-N"),
    ),
    Measurement(
        id="strain_life",
        name="Strain–life (Coffin–Manson)",
        category="Fatigue",
        summary="Elastic and plastic branches, the four strain-life constants, and the transition "
                "life where the two branches cross.",
        channels=(
            _ch("cycles", "Cycles to failure", "cycles", "cycles", "Nf", "life", "N"),
            _ch("elastic_amplitude", "Elastic strain amplitude", "-", "dimensionless",
                "εe", "elastic amplitude", "elastic strain"),
            _ch("plastic_amplitude", "Plastic strain amplitude", "-", "dimensionless",
                "εp", "plastic amplitude", "plastic strain"),
        ),
        options=(
            Option("modulus", "Young's modulus", "float", None,
                   "Used to convert the elastic branch into σ'f. Leave blank to skip.",
                   minimum=0.0, unit="MPa"),
        ),
        plots=(
            Plot("strain_life", "Strain–life", "Reversals to failure 2N", "reversals",
                 "Strain amplitude", "-",
                 (Series("elastic data", "Elastic, measured", "scatter", "data"),
                  Series("plastic data", "Plastic, measured", "scatter", "data"),
                  Series("elastic fit", "Elastic branch", "line", "fit"),
                  Series("plastic fit", "Plastic branch", "line", "fit"),
                  Series("total fit", "Total strain", "line", "fit")),
                 xscale="log", yscale="log",
                 note="The branch crossing is the transition life."),
        ),
        analyser=C.fit_strain_life,
        reference="Omranpour et al. (2024a), Eqs. 4–5",
        sample="fatigue_strain_life.csv",
        tags=("fatigue", "Coffin-Manson", "transition life"),
    ),
    Measurement(
        id="power_law",
        name="Density scaling of modulus",
        category="Mechanical",
        summary="Gibson–Ashby style power-law fit of modulus against relative density, with the "
                "exponent's confidence interval.",
        channels=(
            _ch("density", "Bulk density", "g/cm^3", "density", "ρb", "rho", "apparent density"),
            _ch("modulus", "Modulus", "MPa", "stress", "E", "Young's modulus", "stiffness"),
        ),
        options=(
            Option("rho_solid", "Skeletal density", "float", None,
                   "If given, the fit is plotted against relative density ρ/ρs.",
                   minimum=0.0, unit="g/cm^3"),
        ),
        plots=(
            Plot("scaling", "Modulus versus density", "Density", "g/cm³", "Modulus", "MPa",
                 (Series("data", "Measured", "scatter", "data"),
                  Series("fit", "Power-law fit", "line", "fit")),
                 xscale="log", yscale="log"),
        ),
        analyser=C.fit_power_law_scaling,
        reference="Gibson & Ashby (1997); Omranpour et al. (2025), §3.5",
        sample="density_scaling.csv",
        tags=("Gibson-Ashby", "scaling", "density"),
    ),

    # ------------------------------------------------------------ thermal
    Measurement(
        id="tga",
        name="Thermogravimetric analysis",
        category="Thermal & chemical",
        summary="Decomposition thresholds, onset temperature, residue and DTG peaks.",
        channels=(
            _ch("temperature", "Temperature", "°C", "temperature", "T", "sample temperature"),
            _ch("weight_pct", "Weight", "%", "dimensionless",
                "mass", "weight (%)", "residual mass", "TG"),
        ),
        options=(
            Option("thresholds", "Loss thresholds", "range", (5.0, 10.0, 50.0, 65.0),
                   "Mass-loss percentages to report a temperature for."),
        ),
        plots=(
            Plot("tga", "TGA", "Temperature", "°C", "Weight", "%",
                 (Series("TGA", "Weight", "line", "data"),)),
            Plot("dtg", "Derivative (DTG)", "Temperature", "°C",
                 "Rate of mass loss", "%/°C",
                 (Series("DTG", "dW/dT", "line", "data"),),
                 note="Peaks mark the fastest decomposition steps."),
        ),
        analyser=C.analyze_tga,
        reference="Omranpour et al. (2024b), §3.5; (2025), Fig. 5",
        sample="tga_TPU_aerogel.csv",
        tags=("TGA", "DTG", "decomposition", "residue"),
    ),
    Measurement(
        id="dsc",
        name="Differential scanning calorimetry",
        category="Thermal & chemical",
        summary="Melting and crystallisation peaks with baseline-corrected enthalpies, plus a "
                "glass-transition estimate.",
        channels=(
            _ch("temperature", "Temperature", "°C", "temperature", "T", "sample temperature"),
            _ch("heat_flow", "Heat flow", "W/g", "dimensionless",
                "heat flow (W/g)", "DSC", "normalised heat flow", "mW/mg"),
        ),
        options=(
            Option("heating_rate", "Heating rate", "float", 10.0,
                   "Needed to turn the peak area into J/g.", minimum=0.1, maximum=200.0,
                   unit="°C/min"),
            Option("exo_up", "Exotherm points up", "bool", False,
                   "Tick if the instrument plots exotherms upward."),
        ),
        plots=(
            Plot("dsc", "DSC thermogram", "Temperature", "°C", "Heat flow", "W/g",
                 (Series("DSC", "Heat flow", "line", "data"),
                  Series("smoothed", "Smoothed", "line", "fit")),
                 note="Endotherm down unless the exo-up option is set."),
        ),
        analyser=C.analyze_dsc,
        reference="Omranpour et al. (2024a), §3.2",
        sample="dsc_TPU.csv",
        tags=("DSC", "melting", "enthalpy", "Tg"),
    ),
    Measurement(
        id="thermal_point",
        name="Thermal property set",
        category="Thermal & chemical",
        summary="Diffusivity, effusivity, volumetric heat capacity, R-value and clo from "
                "conductivity, density and heat capacity — one row per sample.",
        channels=(
            _ch("k_mw_mk", "Thermal conductivity", "mW/(m·K)", "thermal_conductivity",
                "k", "lambda", "conductivity"),
            _ch("density_g_cm3", "Bulk density", "g/cm^3", "density", "ρb", "rho"),
            _ch("cp_j_kgk", "Specific heat", "J/(kg·K)", "specific_heat", "cp", "heat capacity"),
            _ch("thickness_mm", "Thickness", "mm", "length", "t", "sample thickness",
                required=False, help="Optional — only needed for R-value and clo."),
        ),
        plots=(),
        analyser=C.analyze_thermal_point,
        kind="table",
        reference="Omranpour et al. (2025), Eqs. 8–10; (2024b), Eq. 5",
        sample="thermal_samples.csv",
        tags=("conductivity", "diffusivity", "effusivity", "R-value"),
    ),

    # ------------------------------------------------------------ structure
    Measurement(
        id="sorption",
        name="N₂ sorption / BET",
        category="Structure & porosity",
        summary="Multipoint BET surface area with its C constant and fit quality, total pore "
                "volume by the Gurvich rule and the mean pore diameter.",
        channels=(
            _ch("p_p0", "Relative pressure", "-", "dimensionless",
                "p/p0", "relative pressure", "P/Po", "x"),
            _ch("volume_stp", "Adsorbed volume", "cm^3/g", "specific_volume",
                "quantity adsorbed", "volume STP", "Va", "V"),
        ),
        options=(
            Option("bet_range", "BET range", "range", (0.05, 0.3),
                   "Relative-pressure window for the multipoint BET fit."),
            Option("pore_volume_at", "Gurvich point", "float", 0.99,
                   "Relative pressure at which total pore volume is read.",
                   minimum=0.5, maximum=0.999),
        ),
        plots=(
            Plot("isotherm", "N₂ adsorption isotherm", "Relative pressure p/p₀", "-",
                 "Adsorbed volume", "cm³/g",
                 (Series("isotherm", "Isotherm", "scatter+line", "data"),)),
            Plot("bet", "BET plot", "Relative pressure p/p₀", "-",
                 "1 / [V(p₀/p − 1)]", "g/cm³",
                 (Series("BET plot", "BET points", "scatter", "data"),
                  Series("BET fit", "Linear fit", "line", "fit")),
                 note="A straight line over the fitted window is the BET validity check."),
        ),
        analyser=C.analyze_sorption_bet,
        reference="Omranpour et al. (2024a), Table 1; Brunauer et al. (1938)",
        sample="bet_isotherm.csv",
        tags=("BET", "surface area", "pore volume", "isotherm"),
    ),

    # ------------------------------------------------------------ rheology
    Measurement(
        id="herschel_bulkley",
        name="Flow curve (Herschel–Bulkley)",
        category="Rheology",
        summary="Yield stress, consistency index and flow index of a spinning dope, with the "
                "apparent viscosity at 1 s⁻¹.",
        channels=(
            _ch("shear_rate", "Shear rate", "1/s", "shear_rate", "γ̇", "gamma dot", "rate"),
            _ch("shear_stress", "Shear stress", "Pa", "pressure", "τ", "tau", "stress"),
        ),
        plots=(
            Plot("flow", "Flow curve", "Shear rate", "s⁻¹", "Shear stress", "Pa",
                 (Series("flow curve", "Measured", "scatter", "data"),
                  Series("HB fit", "Herschel–Bulkley fit", "line", "fit")),
                 xscale="log", yscale="log"),
        ),
        analyser=C.fit_herschel_bulkley,
        reference="Omranpour et al. (2025), §2.3 and Fig. 2",
        sample="flow_curve_dope.csv",
        tags=("rheology", "yield stress", "spinnability"),
    ),
    Measurement(
        id="crossover",
        name="Amplitude sweep / flow point",
        category="Rheology",
        summary="Plateau storage modulus and the G′ = G″ crossover that marks the flow point.",
        channels=(
            _ch("x", "Oscillation stress", "Pa", "pressure",
                "shear stress", "strain", "angular frequency", "γ", "ω"),
            _ch("g_storage", "Storage modulus G′", "Pa", "modulus", "G'", "Gp", "elastic modulus"),
            _ch("g_loss", "Loss modulus G″", "Pa", "modulus", "G''", "Gpp", "viscous modulus"),
        ),
        options=(
            Option("x_label", "X-axis name", "choice", "Oscillation stress",
                   "What was swept.", choices=("Oscillation stress", "Shear strain",
                                               "Angular frequency")),
            Option("x_unit", "X-axis unit", "choice", "Pa",
                   "Unit of the swept variable.", choices=("Pa", "%", "rad/s")),
        ),
        plots=(
            Plot("sweep", "Amplitude sweep", "Oscillation stress", "Pa", "Modulus", "Pa",
                 (Series("G'", "G′ (storage)", "scatter+line", "data"),
                  Series("G''", "G″ (loss)", "scatter+line", "data")),
                 xscale="log", yscale="log",
                 note="Where the two traces cross, the gel starts to flow."),
        ),
        analyser=C.find_moduli_crossover,
        reference="Omranpour et al. (2025), §3.2",
        sample="amplitude_sweep.csv",
        tags=("rheology", "crossover", "flow point", "LVER"),
    ),
)

CATEGORIES: tuple[str, ...] = tuple(dict.fromkeys(m.category for m in MEASUREMENTS))
_BY_ID = {m.id: m for m in MEASUREMENTS}


def get(measurement_id: str) -> Measurement:
    try:
        return _BY_ID[measurement_id]
    except KeyError:
        raise KeyError(f"Unknown measurement {measurement_id!r}. "
                       f"Known: {', '.join(sorted(_BY_ID))}") from None


def by_category() -> dict[str, list[Measurement]]:
    out: dict[str, list[Measurement]] = {c: [] for c in CATEGORIES}
    for m in MEASUREMENTS:
        out[m.category].append(m)
    return out


def search(query: str) -> list[Measurement]:
    """Rank measurements by how well they match a free-text query."""
    q = _norm(query)
    if not q:
        return list(MEASUREMENTS)
    terms = q.split()
    scored: list[tuple[float, Measurement]] = []
    for m in MEASUREMENTS:
        haystacks = ((_norm(m.name), 4.0), (_norm(" ".join(m.tags)), 3.0),
                     (_norm(m.category), 2.0), (_norm(m.summary), 1.0),
                     (_norm(" ".join(c.label for c in m.channels)), 1.5))
        score = 0.0
        for term in terms:
            for hay, weight in haystacks:
                if term in hay:
                    score += weight * (1.5 if hay.startswith(term) else 1.0)
        if score:
            scored.append((score, m))
    scored.sort(key=lambda t: (-t[0], t[1].name))
    return [m for _s, m in scored]
