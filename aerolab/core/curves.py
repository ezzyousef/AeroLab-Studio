"""Curve analysers: turn raw instrument data into the numbers the papers report.

Each analyser takes plain numpy arrays, validates them, and returns an `AnalysisResult`
holding metrics (value + unit + note) and derived curves ready for plotting or export.
They are deliberately independent of the GUI so they can be unit-tested and scripted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
from scipy import optimize, signal, stats

__all__ = [
    "Metric", "AnalysisResult", "ANALYSERS",
    "analyze_stress_strain", "analyze_cyclic_tension", "fit_sn_basquin", "fit_strain_life",
    "analyze_tga", "analyze_dsc", "analyze_sorption_bet", "fit_herschel_bulkley",
    "find_moduli_crossover", "analyze_thermal_point", "fit_power_law_scaling",
]

N2_CROSS_SECTION = 0.162e-18   # m^2 per N2 molecule at 77 K
AVOGADRO = 6.02214076e23
MOLAR_VOLUME_STP = 22414.0     # cm^3/mol
N2_LIQUID_FACTOR = 0.0015468   # cm^3 liquid per cm^3 STP
_WIDTH_CAP = 6.0               # a DSC peak may not be integrated beyond 6x its half-width


@dataclass
class Metric:
    name: str
    value: float
    unit: str = ""
    note: str = ""

    def as_row(self) -> tuple[str, float, str, str]:
        return self.name, self.value, self.unit, self.note


@dataclass
class AnalysisResult:
    kind: str
    metrics: list[Metric] = field(default_factory=list)
    curves: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def value(self, name: str, default: float | None = None) -> float | None:
        for m in self.metrics:
            if m.name == name:
                return m.value
        return default

    def as_dict(self) -> dict[str, float]:
        return {m.name: m.value for m in self.metrics}

    def table(self) -> list[tuple[str, float, str, str]]:
        return [m.as_row() for m in self.metrics]


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------
def _clean_xy(x: Sequence[float], y: Sequence[float], sort: bool = True, name: str = "data") -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if x.size != y.size:
        raise ValueError(f"{name}: x and y must have the same length ({x.size} vs {y.size})")
    if x.size < 3:
        raise ValueError(f"{name}: need at least 3 points, got {x.size}")
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 3:
        raise ValueError(f"{name}: fewer than 3 finite points after cleaning")
    if sort:
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
    return x, y


def _r2(y: np.ndarray, fit: np.ndarray) -> float:
    ss_res = float(np.sum((y - fit) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def _smooth(y: np.ndarray, window: int | None = None, poly: int = 3) -> np.ndarray:
    n = y.size
    if window is None:
        window = max(5, int(n * 0.05) | 1)
    window = min(window if window % 2 else window + 1, n if n % 2 else n - 1)
    if window <= poly + 1 or n < 7:
        return y.copy()
    return signal.savgol_filter(y, window, poly)


def _interp_crossing(x: np.ndarray, y: np.ndarray, level: float) -> float | None:
    """First x where y crosses `level` (linear interpolation)."""
    d = y - level
    sign = np.sign(d)
    idx = np.where(np.diff(sign) != 0)[0]
    if idx.size == 0:
        return None
    i = int(idx[0])
    x0, x1, y0, y1 = x[i], x[i + 1], d[i], d[i + 1]
    if y1 == y0:
        return float(x0)
    return float(x0 - y0 * (x1 - x0) / (y1 - y0))


# ---------------------------------------------------------------------------
# 1. tensile stress-strain
# ---------------------------------------------------------------------------
def analyze_stress_strain(strain_pct: Sequence[float], stress_mpa: Sequence[float], *,
                          modulus_range: tuple[float, float] | None = None,
                          offset_yield: float = 0.002, min_window: int = 8) -> AnalysisResult:
    """Modulus, strength, elongation, toughness and offset yield from one tensile curve.

    strain_pct: engineering strain in %, stress_mpa: engineering stress in MPa.
    `modulus_range` fixes the fit window in % strain; otherwise the most linear
    early segment is found automatically (highest R² sliding window).
    """
    e, s = _clean_xy(strain_pct, stress_mpa, sort=False, name="stress-strain")
    if np.any(np.diff(e) < 0):
        order = np.argsort(e, kind="stable")
        e, s = e[order], s[order]

    i_max = int(np.argmax(s))
    uts = float(s[i_max])
    strain_at_uts = float(e[i_max])
    eab = float(e[-1])

    # Young's modulus -------------------------------------------------------
    if modulus_range is not None:
        lo, hi = modulus_range
        mask = (e >= lo) & (e <= hi)
        if mask.sum() < 3:
            raise ValueError("modulus_range selects fewer than 3 points")
        fit = stats.linregress(e[mask] / 100.0, s[mask])
        modulus, r2, window = float(fit.slope), float(fit.rvalue ** 2), (float(lo), float(hi))
    else:
        modulus, r2, window = _auto_modulus(e, s, min_window)

    # offset yield ----------------------------------------------------------
    yield_stress = yield_strain = float("nan")
    if math.isfinite(modulus) and modulus > 0:
        offset_line = modulus * (e / 100.0 - offset_yield)
        diff = s - offset_line
        cross = _interp_crossing(e, diff, 0.0)
        if cross is not None and cross > offset_yield * 100.0:
            yield_strain = float(cross)
            yield_stress = float(np.interp(cross, e, s))

    toughness = float(np.trapezoid(s, e / 100.0))              # MJ/m^3
    resilience = float("nan")
    if math.isfinite(yield_strain):
        m = e <= yield_strain
        if m.sum() >= 2:
            resilience = float(np.trapezoid(s[m], e[m] / 100.0))

    metrics = [
        Metric("Young's modulus", modulus, "MPa", f"linear fit {window[0]:.2f}–{window[1]:.2f} % strain, R² = {r2:.4f}"),
        Metric("Ultimate tensile strength", uts, "MPa"),
        Metric("Strain at UTS", strain_at_uts, "%"),
        Metric("Elongation at break", eab, "%"),
        Metric("Toughness", toughness, "MJ/m^3", "area under the curve"),
        Metric("Yield stress", yield_stress, "MPa", f"{offset_yield * 100:.1f} % offset"),
        Metric("Yield strain", yield_strain, "%"),
        Metric("Resilience", resilience, "MJ/m^3", "area up to yield"),
        Metric("Specific strength", uts, "MPa", "divide by density for MPa·cm³/g"),
    ]
    curves = {
        "stress-strain": (e, s),
        "modulus fit": (np.array(window), np.array(window) / 100.0 * modulus),
    }
    return AnalysisResult("stress_strain", metrics, curves,
                          {"points": int(e.size), "modulus_window": window, "modulus_r2": r2})


def _auto_modulus(e: np.ndarray, s: np.ndarray, min_window: int) -> tuple[float, float, tuple[float, float]]:
    """Initial tangent modulus: the most linear early window whose slope is near the steepest.

    Windows of several lengths are tried inside the first part of the curve. Requiring the
    slope to be close to the steepest early slope keeps the fit on the initial elastic
    region instead of drifting onto a flatter, equally straight part further along.
    """
    n = e.size
    if n < 4:
        return float("nan"), float("nan"), (float(e[0]), float(e[-1]))

    search_limit = max(4, int(n * 0.5))                       # only the first half of the curve
    lengths = sorted({max(4, min_window // 2), min_window, int(n * 0.05), int(n * 0.10), int(n * 0.15)})
    lengths = [L for L in lengths if 3 < L <= max(4, search_limit)]
    if not lengths:
        lengths = [max(4, min(search_limit, n // 2))]

    candidates: list[tuple[float, float, tuple[float, float]]] = []   # (slope, r2, window)
    for win in lengths:
        for start in range(0, max(1, search_limit - win + 1)):
            stop = start + win
            seg_e, seg_s = e[start:stop] / 100.0, s[start:stop]
            if seg_e.size < 3 or np.ptp(seg_e) <= 0:
                continue
            fit = stats.linregress(seg_e, seg_s)
            if fit.slope > 0:
                candidates.append((float(fit.slope), float(fit.rvalue ** 2), (float(e[start]), float(e[stop - 1]))))
    if not candidates:
        idx = max(2, int(n * 0.05))
        slope = float((s[idx] - s[0]) / ((e[idx] - e[0]) / 100.0)) if e[idx] != e[0] else float("nan")
        return slope, float("nan"), (float(e[0]), float(e[idx]))

    steepest = max(c[0] for c in candidates)
    near_steepest = [c for c in candidates if c[0] >= 0.7 * steepest]
    best = max(near_steepest or candidates, key=lambda c: c[1])
    return best[0], best[1], best[2]


# ---------------------------------------------------------------------------
# 2. cyclic tension (hysteresis, permanent set, elastic recovery)
# ---------------------------------------------------------------------------
def analyze_cyclic_tension(strain_pct: Sequence[float], stress_mpa: Sequence[float], *,
                           zero_stress_fraction: float = 0.02) -> AnalysisResult:
    """Per-cycle permanent set, elastic recovery and hysteresis energy.

    Cycles are segmented at strain maxima; the permanent set of each cycle is the strain
    at which stress falls back to `zero_stress_fraction` of that cycle's peak stress.
    """
    e, s = _clean_xy(strain_pct, stress_mpa, sort=False, name="cyclic")
    span = max(1e-12, float(np.ptp(e)))
    peaks, _ = signal.find_peaks(e, prominence=0.1 * span)
    if peaks.size == 0:
        peaks = np.array([int(np.argmax(e))])
    # cycle boundaries are the strain minima between successive peaks
    bounds = [0]
    for left, right in zip(peaks[:-1], peaks[1:]):
        bounds.append(int(left + np.argmin(e[left:right + 1])))
    bounds.append(e.size - 1)
    bounds = sorted(set(int(min(max(b, 0), e.size - 1)) for b in bounds))

    rows: list[dict[str, float]] = []
    loops: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for n, (start, stop) in enumerate(zip(bounds[:-1], bounds[1:]), start=1):
        seg_e, seg_s = e[start:stop + 1], s[start:stop + 1]
        if seg_e.size < 5:
            continue
        i_peak = int(np.argmax(seg_e))
        peak_strain = float(seg_e[i_peak])
        peak_stress = float(np.max(seg_s))
        unload_e, unload_s = seg_e[i_peak:], seg_s[i_peak:]
        # Permanent set = strain where the unloading branch reaches zero load. Normally that is
        # simply the end of the branch; if the test never unloads fully, extrapolate to sigma = 0.
        ps = float("nan")
        if unload_e.size >= 2:
            threshold = zero_stress_fraction * peak_stress
            unloaded = np.flatnonzero(unload_s <= threshold)
            if unloaded.size:
                # The furthest the fibre sprang back. Taking the smallest strain (rather than the
                # first sub-threshold point) keeps the answer stable when the load cell noise floor
                # makes the tail of the branch read zero for many points.
                ps = float(unload_e[unloaded].min())
            else:
                # Never fully unloaded: extrapolate the measured tail down to sigma = 0.
                j_min = int(np.argmin(unload_s))
                ps = float(unload_e[j_min])
                tail = slice(max(0, j_min - max(3, unload_e.size // 10)), j_min + 1)
                xt, yt = unload_e[tail], unload_s[tail]
                if xt.size >= 2 and np.ptp(yt) > 0:
                    slope = np.polyfit(yt, xt, 1)[0]
                    ps = float(unload_e[j_min] - slope * unload_s[j_min])
        area_load = float(np.trapezoid(seg_s[:i_peak + 1], seg_e[:i_peak + 1] / 100.0))
        area_unload = float(np.trapezoid(unload_s, unload_e / 100.0))
        hysteresis = abs(area_load) - abs(area_unload)
        er = peak_strain - ps if math.isfinite(ps) else float("nan")
        rows.append({
            "cycle": n, "peak_strain": peak_strain, "peak_stress": peak_stress,
            "permanent_set": ps, "elastic_recovery": er,
            "er_ratio": er / peak_strain * 100.0 if peak_strain else float("nan"),
            "hysteresis_energy": hysteresis,
            "dissipation_ratio": hysteresis / abs(area_load) * 100.0 if area_load else float("nan"),
        })
        loops[f"cycle {n}"] = (seg_e, seg_s)

    if not rows:
        raise ValueError("cyclic: no complete cycle detected")

    first, last = rows[0], rows[-1]
    metrics = [
        Metric("Cycles detected", float(len(rows)), "cycles"),
        Metric("Permanent set, cycle 1", first["permanent_set"], "%"),
        Metric("Permanent set, last cycle", last["permanent_set"], "%"),
        Metric("Permanent set change", last["permanent_set"] - first["permanent_set"], "%"),
        Metric("ER/εmax, cycle 1", first["er_ratio"], "%"),
        Metric("ER/εmax, last cycle", last["er_ratio"], "%"),
        Metric("ER/εmax change", last["er_ratio"] - first["er_ratio"], "%",
               "negative means recovery degraded over the test"),
        Metric("Hysteresis energy, cycle 1", first["hysteresis_energy"], "MJ/m^3"),
        Metric("Hysteresis energy, last cycle", last["hysteresis_energy"], "MJ/m^3"),
        Metric("Peak stress, cycle 1", first["peak_stress"], "MPa"),
        Metric("Peak stress, last cycle", last["peak_stress"], "MPa"),
        Metric("Stress softening", (first["peak_stress"] - last["peak_stress"]) / first["peak_stress"] * 100.0
               if first["peak_stress"] else float("nan"), "%", "drop in peak stress from first to last cycle"),
        Metric("Ratcheting strain, last cycle", (last["peak_strain"] + last["permanent_set"]) / 2.0, "%",
               "εr = (εmax + εmin)/2"),
    ]
    return AnalysisResult("cyclic_tension", metrics, loops, {"per_cycle": rows})


# ---------------------------------------------------------------------------
# 3. fatigue
# ---------------------------------------------------------------------------
def fit_sn_basquin(cycles: Sequence[float], stress_amplitude: Sequence[float]) -> AnalysisResult:
    """Fit σa = σ'f (2Nf)^b on log–log axes."""
    n, sa = _clean_xy(cycles, stress_amplitude, sort=True, name="S-N")
    if np.any(n <= 0) or np.any(sa <= 0):
        raise ValueError("S-N: cycles and stress amplitudes must be positive")
    if np.ptp(n) <= 0:
        # All the specimens lasted the same number of cycles, so the line has no slope.
        # Refusing beats handing back a NaN exponent that reads like a measurement.
        raise ValueError("S-N: every specimen has the same life, so no Basquin exponent can "
                         "be fitted — at least two different lives are needed")
    fit = stats.linregress(np.log10(2.0 * n), np.log10(sa))
    b = float(fit.slope)
    sigma_f = float(10.0 ** fit.intercept)
    pred = sigma_f * (2.0 * n) ** b
    grid = np.logspace(np.log10(n.min() * 0.5), np.log10(n.max() * 2.0), 200)
    metrics = [
        Metric("Fatigue strength coefficient σ'f", sigma_f, "MPa"),
        Metric("Fatigue strength exponent b", b, "-"),
        Metric("R²", _r2(np.log10(sa), np.log10(pred)), "-"),
        Metric("Predicted life at 50 % of σ'f", float(0.5 * (0.5) ** (1.0 / b)), "cycles"),
    ]
    return AnalysisResult("sn_curve", metrics,
                          {"data": (n, sa), "fit": (grid, sigma_f * (2.0 * grid) ** b)},
                          {"sigma_f": sigma_f, "b": b})


def fit_strain_life(cycles: Sequence[float], elastic_amplitude: Sequence[float],
                    plastic_amplitude: Sequence[float], *, modulus: float | None = None) -> AnalysisResult:
    """Fit the elastic and plastic branches of the strain-life curve."""
    n = np.asarray(cycles, float).ravel()
    ea = np.asarray(elastic_amplitude, float).ravel()
    pa = np.asarray(plastic_amplitude, float).ravel()
    if not (n.size == ea.size == pa.size):
        raise ValueError("strain-life: all three arrays must have the same length")
    ok = np.isfinite(n) & np.isfinite(ea) & np.isfinite(pa) & (n > 0) & (ea > 0) & (pa > 0)
    n, ea, pa = n[ok], ea[ok], pa[ok]
    if n.size < 3:
        raise ValueError("strain-life: need at least 3 valid points")

    el = stats.linregress(np.log10(2.0 * n), np.log10(ea))
    pl = stats.linregress(np.log10(2.0 * n), np.log10(pa))
    b, c = float(el.slope), float(pl.slope)
    sigma_f_over_E = float(10.0 ** el.intercept)
    eps_f = float(10.0 ** pl.intercept)
    sigma_f = sigma_f_over_E * modulus if modulus else float("nan")

    two_nt = float("nan")
    if b != c:
        two_nt = float((eps_f / sigma_f_over_E) ** (1.0 / (b - c)))

    grid = np.logspace(np.log10(max(n.min() * 0.5, 1e-3)), np.log10(n.max() * 5.0), 240)
    metrics = [
        Metric("σ'f / E", sigma_f_over_E, "-"),
        *([Metric("Fatigue strength coefficient σ'f", sigma_f, "MPa",
                  f"σ'f/E × E, with E = {modulus:g} MPa")] if modulus else []),
        Metric("Fatigue strength exponent b", b, "-"),
        Metric("Fatigue ductility coefficient ε'f", eps_f, "-"),
        Metric("Fatigue ductility exponent c", c, "-"),
        Metric("Transition life 2Nt", two_nt, "reversals",
               "below 1 reversal means elastic strain dominates at every practical life"),
        Metric("Elastic branch R²", float(el.rvalue ** 2), "-"),
        Metric("Plastic branch R²", float(pl.rvalue ** 2), "-"),
    ]
    curves = {
        "elastic data": (n, ea), "plastic data": (n, pa),
        "elastic fit": (grid, sigma_f_over_E * (2.0 * grid) ** b),
        "plastic fit": (grid, eps_f * (2.0 * grid) ** c),
        "total fit": (grid, sigma_f_over_E * (2.0 * grid) ** b + eps_f * (2.0 * grid) ** c),
    }
    return AnalysisResult("strain_life", metrics, curves,
                          {"b": b, "c": c, "eps_f": eps_f, "sigma_f_over_E": sigma_f_over_E})


# ---------------------------------------------------------------------------
# 4. TGA
# ---------------------------------------------------------------------------
def analyze_tga(temperature: Sequence[float], weight_pct: Sequence[float], *,
                thresholds: Iterable[float] = (5.0, 10.0, 50.0, 65.0)) -> AnalysisResult:
    """Decomposition temperatures, residue and DTG peaks."""
    T, w = _clean_xy(temperature, weight_pct, sort=True, name="TGA")
    w0 = float(w[0])
    if w0 <= 0:
        raise ValueError("TGA: first weight value must be positive")
    loss = (w0 - w) / w0 * 100.0

    metrics: list[Metric] = []
    for thr in thresholds:
        t_thr = _interp_crossing(T, loss, thr)
        metrics.append(Metric(f"T at {thr:g} % loss", t_thr if t_thr is not None else float("nan"), "°C"))

    dtg = -np.gradient(_smooth(w), T)
    dtg_s = _smooth(dtg)
    peaks, props = signal.find_peaks(dtg_s, prominence=float(np.nanmax(dtg_s)) * 0.08 if np.nanmax(dtg_s) > 0 else None)
    for i, p in enumerate(peaks[:3], start=1):
        metrics.append(Metric(f"DTG peak {i}", float(T[p]), "°C", f"rate {dtg_s[p]:.3f} %/°C"))
    metrics.append(Metric("Residue at final temperature", float(w[-1]), "%", f"at {T[-1]:.0f} °C"))
    metrics.append(Metric("Total mass loss", float(loss[-1]), "%"))
    metrics.append(Metric("Onset temperature", _onset_temperature(T, w), "°C", "intersection of the two tangents"))

    curves = {"TGA": (T, w), "DTG": (T, dtg_s), "mass loss": (T, loss)}
    return AnalysisResult("tga", metrics, curves, {"peaks": [float(T[p]) for p in peaks]})


def _onset_temperature(T: np.ndarray, w: np.ndarray) -> float:
    """Extrapolated onset: intersection of the baseline and the steepest-descent tangent."""
    dw = np.gradient(_smooth(w), T)
    i = int(np.argmin(dw))
    if i <= 1 or i >= T.size - 2:
        return float("nan")
    slope = float(dw[i])
    if slope == 0:
        return float("nan")
    baseline = float(np.mean(w[: max(2, int(T.size * 0.05))]))
    return float(T[i] + (baseline - w[i]) / slope)


# ---------------------------------------------------------------------------
# 5. DSC
# ---------------------------------------------------------------------------
def analyze_dsc(temperature: Sequence[float], heat_flow: Sequence[float], *,
                heating_rate: float = 10.0, exo_up: bool = False,
                peak_window: tuple[float, float] | None = None) -> AnalysisResult:
    """Peak temperatures, enthalpies (linear baseline) and a glass transition estimate.

    heating_rate is in °C/min; heat_flow in W/g. Enthalpy = ∫ q dT / rate.
    """
    T, q = _clean_xy(temperature, heat_flow, sort=True, name="DSC")
    if exo_up:
        q = -q
    rate_s = heating_rate / 60.0
    if rate_s <= 0:
        raise ValueError("DSC: heating rate must be positive")

    qs = _smooth(q)
    lo, hi = peak_window if peak_window else (float(T[0]), float(T[-1]))
    mask = (T >= lo) & (T <= hi)
    Tm_region, q_region = T[mask], qs[mask]
    if Tm_region.size < 5:
        raise ValueError("DSC: peak window contains too few points")

    # Every significant transition, not just the deepest one: a segmented polyurethane melts
    # in two steps, and the second would otherwise be mistaken for the glass transition.
    endo_idx = _significant_peaks(Tm_region, q_region, direction=-1)
    exo_idx = _significant_peaks(Tm_region, q_region, direction=+1)
    i_endo = int(np.argmin(q_region))
    i_exo = int(np.argmax(q_region))
    peak_endo_T = float(Tm_region[i_endo])
    peak_exo_T = float(Tm_region[i_exo])

    dh_endo = _peak_enthalpy(Tm_region, q_region, i_endo, rate_s, direction=-1)
    dh_exo = _peak_enthalpy(Tm_region, q_region, i_exo, rate_s, direction=+1)

    transitions = []
    offset = int(np.flatnonzero(mask)[0])
    windows: list[tuple[int, int]] = []
    for idx_list, direction, kind in ((endo_idx, -1, "endotherm"), (exo_idx, +1, "exotherm")):
        for i in idx_list:
            limits = _peak_limits(Tm_region, q_region, int(i), direction)
            if limits is None:
                continue
            windows.append((limits[0] + offset, limits[1] + offset))
            transitions.append({
                "kind": kind, "T": float(Tm_region[i]),
                "enthalpy": _peak_enthalpy(Tm_region, q_region, int(i), rate_s, direction),
                "onset": float(Tm_region[limits[0]]), "end": float(Tm_region[limits[1]]),
            })
    transitions.sort(key=lambda t: t["T"])
    tg = _glass_transition(T, qs, windows)

    metrics = [
        Metric("Endothermic peak (Tm)", peak_endo_T, "°C"),
        Metric("Melting enthalpy ΔHm", dh_endo, "J/g", "linear baseline between the peak limits"),
        Metric("Exothermic peak (Tc)", peak_exo_T, "°C"),
        Metric("Crystallisation enthalpy ΔHc", dh_exo, "J/g"),
        Metric("Glass transition estimate", tg, "°C",
               "steepest baseline step away from the peaks - always confirm manually"),
        Metric("Heating rate", heating_rate, "°C/min"),
        Metric("Transitions found", float(len(transitions)), "peaks"),
    ]
    for n, tr in enumerate(transitions, start=1):
        metrics.append(Metric(f"Transition {n} ({tr['kind']})", tr["T"], "°C",
                              f"ΔH = {tr['enthalpy']:.2f} J/g over {tr['onset']:.1f}–{tr['end']:.1f} °C"))
    curves = {"DSC": (T, q), "smoothed": (T, qs)}
    return AnalysisResult("dsc", metrics, curves,
                          {"exo_up": exo_up, "transitions": transitions})


def _significant_peaks(T: np.ndarray, y: np.ndarray, direction: int,
                       rel_prominence: float = 0.06, limit: int = 6) -> list[int]:
    """Peaks that stand proud of their own local baseline, not just of their neighbours.

    Prominence measured on the raw signal is misleading here: the shallow rise *between*
    two melting endotherms looks enormously prominent because it sits between two deep
    minima, yet it is not an exotherm at all. Each candidate is therefore re-checked
    against the chord through its own limits.
    """
    span = float(np.ptp(y))
    if span <= 0 or y.size < 8:
        return []
    idx, _props = signal.find_peaks(y if direction > 0 else -y,
                                    prominence=rel_prominence * span,
                                    distance=max(3, y.size // 100))
    if idx.size == 0:
        return []
    baseline = _instrument_baseline(T, y)
    kept: list[tuple[float, int]] = []
    for i in idx:
        i = int(i)
        # It must depart from the instrument baseline, in the right direction, by enough
        # to be a transition rather than the shallow rise between two neighbouring peaks.
        departure = float(y[i] - baseline[i])
        if direction * departure < rel_prominence * span:
            continue
        limits = _peak_limits(T, y, i, direction)
        if limits is None:
            continue
        kept.append((abs(departure), i))
    kept.sort(reverse=True)
    return sorted(i for _h, i in kept[:limit])


def _instrument_baseline(T: np.ndarray, y: np.ndarray) -> np.ndarray:
    """A straight trend line through the flat parts of the trace.

    Peaks are steep, baseline is not, so fitting only the flattest half of the points
    gives a line that follows the instrument drift and ignores the transitions.
    """
    grad = np.abs(_smooth(np.gradient(y, T)))
    quiet = grad <= np.median(grad)
    if quiet.sum() < 4:
        quiet = np.ones_like(grad, dtype=bool)
    slope, intercept = np.polyfit(T[quiet], y[quiet], 1)
    return slope * T + intercept


def _glass_transition(T: np.ndarray, qs: np.ndarray, peak_windows: Sequence[tuple[int, int]]) -> float:
    """Steepest baseline step below the first melting or crystallisation peak.

    A Tg is a small change in the *level* of the baseline; a melt is a large change in
    *area*. Taking the steepest gradient outright just re-finds the flank of the melting
    peak, so every located peak is masked out — and, because in a polymer scan the glass
    transition is the lowest-temperature feature, so is everything above the first one.
    """
    if T.size < 12:
        return float("nan")
    quiet = np.ones(T.size, dtype=bool)
    for left, right in peak_windows:
        quiet[max(0, left):min(T.size, right + 1)] = False
    if peak_windows:
        quiet[min(left for left, _r in peak_windows):] = False
    edge = max(3, T.size // 50)               # ignore the ramp-in/ramp-out artefacts
    quiet[:edge] = False
    quiet[-edge:] = False
    if quiet.sum() < 5:
        return float("nan")
    d1 = np.abs(_smooth(np.gradient(qs, T)))
    candidates = np.flatnonzero(quiet)
    return float(T[candidates[int(np.argmax(d1[candidates]))]])


def _peak_limits(T: np.ndarray, q: np.ndarray, i_peak: int, direction: int,
                 shoulder_fraction: float = 0.02) -> tuple[int, int] | None:
    """Where one peak starts and ends: walk out to the nearest turning point on each side.

    This is the limits-and-chord construction DSC software uses. Walking to the turning
    points rather than to a fixed offset from a global baseline is what keeps two
    overlapping melts, or a melt sitting on a glass-transition step, from being merged
    into one enormous peak.
    """
    n = T.size
    if n < 5 or not (0 <= i_peak < n):
        return None
    grad = _smooth(np.gradient(q, T))
    span = float(np.ptp(q))
    flat = shoulder_fraction * span / max(float(np.ptp(T)), 1e-12)

    left = i_peak
    while left > 0 and direction * grad[left - 1] > -flat:
        left -= 1
    right = i_peak
    while right < n - 1 and direction * grad[right + 1] < flat:
        right += 1
    if right - left < 2:
        return None

    residual = q - _chord(T, q, left, right)
    height = float(residual[i_peak])
    if direction * height <= 0:
        return None

    # A turning point can be a long way off when the peak sits on a glass-transition step,
    # which would drag the chord badly off the baseline. Cap the window at a few peak
    # widths instead. The chord still spans the full width, so no tail area is lost.
    half_level = abs(height) / 2.0
    hl = i_peak                       # contiguous walk, so a step elsewhere cannot widen it
    while hl > left and abs(residual[hl - 1]) >= half_level:
        hl -= 1
    hr = i_peak
    while hr < right and abs(residual[hr + 1]) >= half_level:
        hr += 1
    hwhm = max(float(T[hr] - T[hl]) / 2.0, float(np.ptp(T)) / T.size)
    lo_T, hi_T = T[i_peak] - _WIDTH_CAP * hwhm, T[i_peak] + _WIDTH_CAP * hwhm
    left = max(left, int(np.searchsorted(T, lo_T, side="left")))
    right = min(right, int(np.searchsorted(T, hi_T, side="right")) - 1)
    return (left, right) if right - left >= 2 else None


def _chord(T: np.ndarray, q: np.ndarray, left: int, right: int) -> np.ndarray:
    """Straight baseline through the two peak limits, evaluated over the whole array."""
    x0, x1 = float(T[left]), float(T[right])
    y0, y1 = float(q[left]), float(q[right])
    if x1 == x0:
        return np.full_like(T, y0)
    return y0 + (T - x0) * (y1 - y0) / (x1 - x0)


def _peak_enthalpy(T: np.ndarray, q: np.ndarray, i_peak: int, rate_s: float, direction: int,
                   shoulder_fraction: float = 0.02) -> float:
    """Integrate one peak against the chord through its limits. Returns J/g."""
    limits = _peak_limits(T, q, i_peak, direction, shoulder_fraction)
    if limits is None:
        return float("nan")
    left, right = limits
    residual = q - _chord(T, q, left, right)
    area = float(np.trapezoid(residual[left:right + 1], T[left:right + 1]))
    return abs(area / rate_s)


# ---------------------------------------------------------------------------
# 6. N2 sorption / BET
# ---------------------------------------------------------------------------
def analyze_sorption_bet(p_p0: Sequence[float], volume_stp: Sequence[float], *,
                         bet_range: tuple[float, float] = (0.05, 0.30),
                         pore_volume_at: float = 0.99) -> AnalysisResult:
    """Multipoint BET surface area, C constant, Gurvich pore volume and 4V/S pore size."""
    x, v = _clean_xy(p_p0, volume_stp, sort=True, name="sorption")
    if np.any(x <= 0) or np.any(x >= 1):
        raise ValueError("sorption: relative pressure must be between 0 and 1")
    lo, hi = bet_range
    mask = (x >= lo) & (x <= hi)
    if mask.sum() < 3:
        raise ValueError(f"sorption: only {int(mask.sum())} points inside the BET range {lo}-{hi}")

    y = 1.0 / (v * (1.0 / x - 1.0))
    fit = stats.linregress(x[mask], y[mask])
    slope, intercept = float(fit.slope), float(fit.intercept)
    if slope + intercept <= 0:
        raise ValueError("sorption: BET fit is not physical (slope + intercept <= 0)")
    v_m = 1.0 / (slope + intercept)
    c_const = 1.0 + slope / intercept if intercept else float("inf")
    surface = v_m * AVOGADRO * N2_CROSS_SECTION / MOLAR_VOLUME_STP        # m^2/g

    i_close = int(np.argmin(np.abs(x - pore_volume_at)))
    v_pore = float(v[i_close] * N2_LIQUID_FACTOR)
    d_pore = 4.0 * v_pore * 1e-6 / surface * 1e9 if surface > 0 else float("nan")

    metrics = [
        Metric("BET surface area", float(surface), "m^2/g", f"fit over p/p₀ = {lo}–{hi}, R² = {fit.rvalue ** 2:.4f}"),
        Metric("Monolayer volume Vm", float(v_m), "cm^3/g", "STP"),
        Metric("BET C constant", float(c_const), "-", "negative or tiny C means the fit range is wrong"),
        Metric("Total pore volume", v_pore, "cm^3/g", f"Gurvich rule at p/p₀ ≈ {x[i_close]:.3f}"),
        Metric("Mean pore diameter", float(d_pore), "nm", "4V/S, cylindrical pores"),
        Metric("BET fit R²", float(fit.rvalue ** 2), "-"),
    ]
    curves = {
        "isotherm": (x, v),
        "BET plot": (x[mask], y[mask]),
        "BET fit": (x[mask], intercept + slope * x[mask]),
    }
    return AnalysisResult("sorption", metrics, curves, {"slope": slope, "intercept": intercept})


# ---------------------------------------------------------------------------
# 7. rheology
# ---------------------------------------------------------------------------
def fit_herschel_bulkley(shear_rate: Sequence[float], shear_stress: Sequence[float]) -> AnalysisResult:
    """Fit τ = τy + K γ̇ⁿ (and report the power-law fit for comparison)."""
    g, t = _clean_xy(shear_rate, shear_stress, sort=True, name="flow curve")
    if np.any(g < 0):
        raise ValueError("flow curve: shear rate must be non-negative")

    def model(x, tau_y, k, n):
        return tau_y + k * np.power(np.clip(x, 1e-12, None), n)

    tau_y0 = max(float(np.min(t)) * 0.8, 0.0)
    k0 = max((float(np.max(t)) - tau_y0) / max(float(np.max(g)) ** 0.5, 1e-9), 1e-6)
    try:
        popt, pcov = optimize.curve_fit(model, g, t, p0=[tau_y0, k0, 0.5],
                                        bounds=([0.0, 1e-12, 1e-3], [np.inf, np.inf, 3.0]), maxfev=20000)
        perr = np.sqrt(np.diag(pcov))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"flow curve: Herschel-Bulkley fit failed ({exc})") from exc

    tau_y, k, n = (float(v) for v in popt)
    pred = model(g, *popt)
    grid = np.linspace(max(g.min(), 1e-6), g.max(), 200)

    metrics = [
        Metric("Yield stress τy", tau_y, "Pa", f"± {perr[0]:.3g}"),
        Metric("Consistency index K", k, "Pa·sⁿ", f"± {perr[1]:.3g}"),
        Metric("Flow index n", n, "-", "n < 1 is shear-thinning"),
        Metric("R²", _r2(t, pred), "-"),
        Metric("Apparent viscosity at 1 s⁻¹", float(model(1.0, *popt)), "Pa·s"),
    ]
    curves = {"flow curve": (g, t), "HB fit": (grid, model(grid, *popt))}
    return AnalysisResult("herschel_bulkley", metrics, curves,
                          {"tau_y": tau_y, "K": k, "n": n, "errors": perr.tolist()})


def find_moduli_crossover(x: Sequence[float], g_storage: Sequence[float],
                          g_loss: Sequence[float], *, x_label: str = "Oscillation stress",
                          x_unit: str = "Pa") -> AnalysisResult:
    """Locate the G′ = G″ flow point of an amplitude or frequency sweep."""
    xa = np.asarray(x, float).ravel()
    gp = np.asarray(g_storage, float).ravel()
    gpp = np.asarray(g_loss, float).ravel()
    if not (xa.size == gp.size == gpp.size):
        raise ValueError("crossover: all three arrays must have the same length")
    ok = np.isfinite(xa) & np.isfinite(gp) & np.isfinite(gpp) & (xa > 0) & (gp > 0) & (gpp > 0)
    xa, gp, gpp = xa[ok], gp[ok], gpp[ok]
    if xa.size < 3:
        raise ValueError("crossover: need at least 3 valid points")
    order = np.argsort(xa)
    xa, gp, gpp = xa[order], gp[order], gpp[order]

    ratio = np.log10(gp) - np.log10(gpp)
    cross_log = _interp_crossing(np.log10(xa), ratio, 0.0)
    crossover = float(10.0 ** cross_log) if cross_log is not None else float("nan")
    g_at_cross = float(np.interp(crossover, xa, gp)) if math.isfinite(crossover) else float("nan")
    plateau = float(np.median(gp[: max(3, xa.size // 5)]))

    metrics = [
        Metric("Flow point (G′ = G″)", crossover, x_unit, f"{x_label} at the crossover"),
        Metric("Modulus at crossover", g_at_cross, "Pa"),
        Metric("Plateau G′", plateau, "Pa", "median of the first 20 % of points"),
        Metric("tan δ at first point", float(gpp[0] / gp[0]), "-"),
        Metric("Solid-like", 1.0 if gp[0] > gpp[0] else 0.0, "-", "1 = G′ > G″ at low amplitude"),
    ]
    curves = {"G'": (xa, gp), "G''": (xa, gpp)}
    return AnalysisResult("crossover", metrics, curves, {"crossover": crossover})


# ---------------------------------------------------------------------------
# 8. thermal point measurement + scaling fit
# ---------------------------------------------------------------------------
def analyze_thermal_point(k_mw_mk: float, density_g_cm3: float, cp_j_kgk: float,
                          thickness_mm: float | None = None) -> AnalysisResult:
    """Derive diffusivity, effusivity, R-value and clo from a single Hot Disk measurement."""
    k_si = float(k_mw_mk) * 1e-3
    rho_si = float(density_g_cm3) * 1000.0
    cp = float(cp_j_kgk)
    if min(k_si, rho_si, cp) <= 0:
        raise ValueError("thermal: k, density and cp must be positive")
    alpha = k_si / (rho_si * cp)
    effusivity = math.sqrt(k_si * rho_si * cp)
    metrics = [
        Metric("Thermal conductivity", float(k_mw_mk), "mW/(m·K)"),
        Metric("Thermal diffusivity", alpha * 1e6, "mm^2/s"),
        Metric("Thermal effusivity", effusivity, "W·s^0.5/(m^2·K)"),
        Metric("Volumetric heat capacity", rho_si * cp / 1e6, "MJ/(m^3·K)"),
    ]
    if thickness_mm:
        r_value = (float(thickness_mm) * 1e-3) / k_si
        metrics += [Metric("R-value", r_value, "m^2·K/W"), Metric("Clo value", r_value / 0.155, "clo")]
    return AnalysisResult("thermal_point", metrics, {}, {})


def fit_power_law_scaling(density: Sequence[float], modulus: Sequence[float], *,
                          rho_solid: float | None = None) -> AnalysisResult:
    """Fit E ∝ ρⁿ and report the exponent with a confidence interval.

    Written for the n = 0.78 question in Paper 3: it also reports the density range,
    because an exponent fitted over a narrow range is poorly identified.
    """
    rho, e = _clean_xy(density, modulus, sort=True, name="scaling")
    if np.any(rho <= 0) or np.any(e <= 0):
        raise ValueError("scaling: density and modulus must be positive")
    if np.ptp(rho) <= 0:
        # Every sample has the same density, so no exponent exists. Refusing is better
        # than letting the regression return NaN that looks like a result.
        raise ValueError("scaling: every density is the same, so no exponent can be fitted — "
                         "at least two different densities are needed")
    x = np.log(rho / rho_solid) if rho_solid else np.log(rho)
    fit = stats.linregress(x, np.log(e))
    n = float(fit.slope)
    ci = 1.96 * float(fit.stderr)
    span = float(rho.max() / rho.min())
    grid = np.linspace(rho.min(), rho.max(), 120)
    prefactor = float(np.exp(fit.intercept))
    pred_grid = prefactor * ((grid / rho_solid) ** n if rho_solid else grid ** n)

    note = "well constrained"
    if span < 1.5:
        note = f"density spans only {span:.2f}× — the exponent is weakly identified"
    metrics = [
        Metric("Scaling exponent n", n, "-", f"95 % CI ± {ci:.3f}; {note}"),
        Metric("Prefactor", prefactor, "MPa"),
        Metric("R²", float(fit.rvalue ** 2), "-"),
        Metric("Density span", span, "×", "max/min density in the fit"),
        Metric("Gibson–Ashby reference", 2.0, "-", "open-cell foams"),
        Metric("Silica aerogel reference", 3.5, "-", "typical 3–4"),
    ]
    curves = {"data": (rho, e), "fit": (grid, pred_grid)}
    return AnalysisResult("power_law", metrics, curves, {"n": n, "ci": ci, "span": span})


ANALYSERS = {
    "stress_strain": analyze_stress_strain,
    "cyclic_tension": analyze_cyclic_tension,
    "sn_curve": fit_sn_basquin,
    "strain_life": fit_strain_life,
    "tga": analyze_tga,
    "dsc": analyze_dsc,
    "sorption": analyze_sorption_bet,
    "herschel_bulkley": fit_herschel_bulkley,
    "crossover": find_moduli_crossover,
    "power_law": fit_power_law_scaling,
}
