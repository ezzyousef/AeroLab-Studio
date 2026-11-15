"""Materials studio: multi-event thermal analysis, k–density, porosity summaries and QC.

* `tga_steps`: splits a TGA curve into decomposition steps at the valleys of the DTG
  curve and reports each step's temperature range, DTG peak and mass loss.
* `dsc_event_table`: every DSC transition with its enthalpy, normalised to the polymer
  fraction and turned into a crystallinity when the user supplies ΔH°m (never assumed).
* `fit_k_vs_density`: linear, quadratic and power-law fits of conductivity against
  density, compared by AIC. A minimum is reported only if it lies inside the tested range.
* `porosity_summary`: BET surface area and Gurvich pore volume next to the pore volume
  implied by the densities. Their ratio shows how much of the pore space N₂ actually
  probed, because macropores are invisible to it.
* `lver_limit`: end of the linear viscoelastic region of an amplitude sweep.
* `qc_flags`: sample-specific checks, including missing or stale instrument calibration.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Sequence

import numpy as np
from scipy import signal, stats

from .curves import AnalysisResult, Metric, _clean_xy, _interp_crossing, _merge_duplicate_x, _r2, _smooth

__all__ = ["tga_steps", "dsc_event_table", "fit_k_vs_density", "porosity_summary", "lver_limit",
           "qc_flags", "CALIBRATION_MAX_AGE_DAYS"]

CALIBRATION_MAX_AGE_DAYS = 365


# ---------------------------------------------------------------------------
# TGA: multi-step decomposition
# ---------------------------------------------------------------------------
def tga_steps(temperature: Sequence[float], weight_pct: Sequence[float], *,
              min_step_pct: float = 1.0) -> list[dict[str, float]]:
    """Decomposition steps between DTG valleys.

    Each step runs from one DTG minimum (or the start) to the next (or the end). Its
    mass loss is the drop in weight across that interval, which equals ∫DTG dT over it,
    so the steps add up to the total loss exactly. Steps smaller than `min_step_pct` are
    merged into their neighbour.
    """
    T, w = _clean_xy(temperature, weight_pct, sort=True, name="TGA steps")
    T, w = _merge_duplicate_x(T, w)
    ws = _smooth(w)
    dtg = _smooth(-np.gradient(ws, T))
    top = float(np.nanmax(dtg))
    if not (top > 0):
        return []
    peaks, _ = signal.find_peaks(dtg, prominence=0.05 * top)
    if peaks.size == 0:
        peaks = np.array([int(np.argmax(dtg))])
    bounds = [0]
    for a, b in zip(peaks[:-1], peaks[1:]):
        bounds.append(int(a + np.argmin(dtg[a:b + 1])))
    bounds.append(T.size - 1)
    steps = []
    for i, p in enumerate(peaks):
        lo, hi = bounds[i], bounds[i + 1]
        steps.append({"start": float(T[lo]), "end": float(T[hi]), "peak": float(T[p]),
                      "rate": float(dtg[p]), "loss": float(w[lo] - w[hi])})
    merged: list[dict[str, float]] = []
    for st in steps:
        if merged and st["loss"] < min_step_pct:
            merged[-1]["end"] = st["end"]
            merged[-1]["loss"] += st["loss"]
        elif merged and merged[-1]["loss"] < min_step_pct:
            st = dict(st, start=merged[-1]["start"], loss=st["loss"] + merged[-1]["loss"])
            merged[-1] = st
        else:
            merged.append(dict(st))
    return merged


# ---------------------------------------------------------------------------
# DSC: event table
# ---------------------------------------------------------------------------
def dsc_event_table(transitions: Sequence[dict[str, Any]], *, polymer_fraction: float | None = None,
                    dh100: float | None = None) -> list[dict[str, Any]]:
    """Rows for every DSC transition; crystallinity only when ΔH°m is given."""
    if polymer_fraction is not None and not (0 < polymer_fraction <= 1):
        raise ValueError("polymer fraction must be between 0 and 1")
    if dh100 is not None and dh100 <= 0:
        raise ValueError("ΔH°m (100 % crystalline) must be positive")
    rows = []
    for n, tr in enumerate(sorted(transitions, key=lambda t: t["T"]), start=1):
        dh = float(tr["enthalpy"])
        row = {"event": n, "kind": tr["kind"], "peak": float(tr["T"]), "onset": float(tr["onset"]),
               "end": float(tr["end"]), "enthalpy": dh,
               "enthalpy_per_polymer": dh / polymer_fraction if polymer_fraction else float("nan"),
               "crystallinity": float("nan"), "note": ""}
        if dh100 and tr["kind"] == "endotherm":
            row["crystallinity"] = dh / ((polymer_fraction or 1.0) * dh100) * 100.0
            row["note"] = "X = ΔH/(w·ΔH°m); for TPU hard-segment endotherms this is an upper bound"
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# thermal conductivity against density
# ---------------------------------------------------------------------------
def fit_k_vs_density(density: Sequence[float], conductivity: Sequence[float]) -> AnalysisResult:
    """Linear, quadratic and power-law k(ρ), compared by AIC; minimum only inside the data."""
    rho, k = _clean_xy(density, conductivity, sort=True, name="k vs density")
    if np.any(rho <= 0) or np.any(k <= 0):
        raise ValueError("k vs density: density and conductivity must be positive")
    if np.unique(rho).size < 3:
        raise ValueError("k vs density: need at least 3 different densities")
    n = rho.size

    def aic(rss, p):
        return n * math.log(max(rss, 1e-300) / n) + 2 * (p + 1)

    lin = np.polyfit(rho, k, 1)
    quad = np.polyfit(rho, k, 2)
    pw = stats.linregress(np.log(rho), np.log(k))
    preds = {"linear": np.polyval(lin, rho), "quadratic": np.polyval(quad, rho),
             "power law": np.exp(pw.intercept) * rho ** pw.slope}
    nparams = {"linear": 2, "quadratic": 3, "power law": 2}
    scores = {m: aic(float(np.sum((k - p) ** 2)), nparams[m]) for m, p in preds.items()}
    best = min(scores, key=scores.get)
    metrics = [
        Metric("k slope (linear)", float(lin[0]), "mW/(m·K) per g/cm^3", f"k = {lin[1]:.4g} + {lin[0]:.4g}·ρ"),
        Metric("Power-law exponent", float(pw.slope), "-", f"k = {math.exp(pw.intercept):.4g}·ρ^{pw.slope:.3f}"),
    ]
    rho_min = float("nan")
    note = "no minimum: the quadratic opens downward or is monotonic over the data"
    if quad[0] > 0:
        cand = -quad[1] / (2 * quad[0])
        if rho.min() <= cand <= rho.max():
            rho_min = float(cand)
            note = (f"k_min = {np.polyval(quad, cand):.4g} mW/(m·K) inside the tested range; the classic trade-off "
                    "between solid conduction (rising with ρ) and gas/radiation (falling with ρ)")
        else:
            note = f"the fitted minimum ({cand:.3g} g/cm³) lies outside the tested densities, so it is not reported"
    metrics.append(Metric("Density of minimum k (quadratic)", rho_min, "g/cm^3", note))
    for m in preds:
        metrics.append(Metric(f"AIC, {m}", scores[m], "-",
                              f"ΔAIC = {scores[m] - scores[best]:.2f}; R² = {_r2(k, preds[m]):.4f}"))
    grid = np.linspace(rho.min(), rho.max(), 160)              # tested range only
    curves = {"data": (rho, k), "linear fit": (grid, np.polyval(lin, grid)),
              "quadratic fit": (grid, np.polyval(quad, grid)),
              "power-law fit": (grid, np.exp(pw.intercept) * grid ** pw.slope)}
    if n < 6:
        metrics.append(Metric("Samples", float(n), "samples", "fewer than 6: model choice is weakly determined"))
    return AnalysisResult("k_density", metrics, curves,
                          {"best": best, "aic": scores, "quadratic": quad.tolist(), "rho_min": rho_min})


# ---------------------------------------------------------------------------
# BET / porosity summary
# ---------------------------------------------------------------------------
def porosity_summary(surface_m2_g: float, gurvich_cm3_g: float | None, rho_b: float | None,
                     rho_s: float | None) -> dict[str, dict[str, Any]]:
    """Gas-sorption and density views of the same pore space, side by side."""
    from .equations import get

    out: dict[str, dict[str, Any]] = {
        "BET surface area": {"value": surface_m2_g, "unit": "m^2/g", "source": "BET fit"}}
    if gurvich_cm3_g is not None and math.isfinite(gurvich_cm3_g):
        out["Pore volume, N₂ (Gurvich)"] = {"value": gurvich_cm3_g, "unit": "cm^3/g", "source": "isotherm"}
        out["Mean pore diameter, N₂"] = {
            "value": float(get("pore_diameter").compute(V_p=gurvich_cm3_g, S=surface_m2_g)), "unit": "nm",
            "source": "4V/S with the Gurvich volume"}
    if rho_b and rho_s:
        vp = float(get("pore_volume").compute(rho_b=rho_b, rho_s=rho_s))
        out["Porosity"] = {"value": float(get("porosity_from_density").compute(rho_b=rho_b, rho_s=rho_s)),
                           "unit": "%", "source": "1 − ρb/ρs"}
        out["Pore volume, densities"] = {"value": vp, "unit": "cm^3/g", "source": "1/ρb − 1/ρs"}
        out["Mean pore diameter, densities"] = {
            "value": float(get("pore_diameter").compute(V_p=vp, S=surface_m2_g)), "unit": "nm",
            "source": "4V/S with the density pore volume (the papers' Table 1 method)"}
        if gurvich_cm3_g is not None and math.isfinite(gurvich_cm3_g) and vp > 0:
            frac = gurvich_cm3_g / vp * 100.0
            out["Pore volume seen by N₂"] = {
                "value": frac, "unit": "%",
                "source": "Gurvich ÷ density pore volume; well below 100 % means macropores N₂ cannot fill"}
    return out


# ---------------------------------------------------------------------------
# rheology: linear viscoelastic region
# ---------------------------------------------------------------------------
def lver_limit(x: Sequence[float], g_storage: Sequence[float], *, tolerance: float = 0.1,
               plateau_points: int | None = None) -> dict[str, float]:
    """First x where G′ falls below (1 − tolerance) × its low-amplitude plateau.

    The plateau is the median of the first points (default: the first 20 %, at least 3).
    Interpolated in log–log space. NaN if G′ never leaves the band.
    """
    xa, gp = _clean_xy(x, g_storage, sort=True, name="LVER")
    if np.any(xa <= 0) or np.any(gp <= 0):
        raise ValueError("LVER: amplitude and G′ must be positive")
    k = plateau_points or max(3, xa.size // 5)
    plateau = float(np.median(gp[:k]))
    level = (1.0 - tolerance) * plateau
    cross = _interp_crossing(np.log10(xa), np.log10(gp), math.log10(level))
    return {"plateau": plateau, "limit": float(10 ** cross) if cross is not None else float("nan"),
            "tolerance": tolerance}


# ---------------------------------------------------------------------------
# QC
# ---------------------------------------------------------------------------
def _parse_date(text: str) -> date | None:
    try:
        return datetime.fromisoformat(text).date()
    except (TypeError, ValueError):
        return None


def qc_flags(measurement_id: str, result: AnalysisResult, options: dict | None = None, *,
             experiment=None, sample=None, today: date | None = None) -> list[tuple[str, str]]:
    """[(level, message)]: level is 'warning' or 'info'. An empty list means nothing to flag."""
    options = options or {}
    today = today or date.today()
    flags: list[tuple[str, str]] = []

    # traceability ------------------------------------------------------------
    if experiment is None:
        flags.append(("warning", "Not linked to an experiment: no instrument, operator or calibration on record."))
    else:
        cal = _parse_date(experiment.instrument.calibration_date)
        ref = _parse_date(experiment.date) or today
        if not experiment.instrument.calibration_date:
            flags.append(("warning", f"Calibration of {experiment.instrument.name or 'the instrument'} not recorded."))
        elif cal is None:
            flags.append(("warning", f"Calibration date {experiment.instrument.calibration_date!r} is unreadable."))
        elif (ref - cal).days > CALIBRATION_MAX_AGE_DAYS:
            flags.append(("warning", f"Calibration is {(ref - cal).days} days old at the time of the test "
                                     f"(more than {CALIBRATION_MAX_AGE_DAYS})."))
        elif cal > ref:
            flags.append(("warning", "Calibration date is after the test date."))
    if sample is not None and not sample.bulk_density_g_cm3:
        flags.append(("info", f"Sample {sample.sample_id} has no bulk density: porosity and specific "
                              "properties cannot be derived."))

    value = result.value
    # per measurement ---------------------------------------------------------
    if measurement_id == "stress_strain":
        sens = value("Modulus window sensitivity")
        if sens is not None and math.isfinite(sens) and sens > 10:
            flags.append(("warning", f"Young's modulus varies by {sens:.0f} % (CV) between nearby fit windows."))
        r2 = (result.meta or {}).get("modulus_r2")
        if r2 is not None and math.isfinite(r2) and r2 < 0.99:
            flags.append(("info", f"Modulus fit R² = {r2:.3f} (below 0.99)."))
    elif measurement_id == "dsc":
        if "heating_rate" not in options or options.get("heating_rate") in (None, ""):
            flags.append(("info", "Heating rate left at the default 10 °C/min: enthalpies scale with it, so confirm."))
        if value("Transitions found") == 0:
            flags.append(("warning", "No DSC transition was detected."))
    elif measurement_id == "tga":
        curves = result.curves.get("TGA")
        if curves is not None and options.get("dry_basis_at") in (None, ""):
            T, w = (np.asarray(a, float) for a in curves)
            early = w[T <= 150.0]
            if early.size >= 2 and (early[0] - early.min()) > 1.0:
                flags.append(("warning", f"{early[0] - early.min():.1f} % lost below 150 °C (moisture or solvent) "
                                         "is counted as decomposition; consider a dry basis."))
    elif measurement_id == "sorption":
        problems = (result.meta or {}).get("criteria_problems") or []
        for p in problems:
            flags.append(("warning", f"BET range: {p}."))
        c = value("BET C constant")
        if c is not None and math.isfinite(c) and not (2 <= c <= 1000):
            flags.append(("warning", f"BET C = {c:.3g} is outside 2–1000: the range is probably wrong."))
        if not math.isfinite(value("Total pore volume", float("nan")) or float("nan")):
            flags.append(("info", "The isotherm stops before the Gurvich point: no total pore volume."))
    elif measurement_id in ("sn_curve", "strain_life"):
        data = result.curves.get("data") or result.curves.get("elastic data")
        if data is not None and len(data[0]) < 6:
            flags.append(("warning", f"Only {len(data[0])} specimens: fatigue constants are weakly determined "
                                     "(ASTM E739 recommends replicated tests at several levels)."))
        if (result.meta or {}).get("prediction_inside_range") is False:
            flags.append(("info", "The reported predicted life is an extrapolation beyond the tested lives."))
    elif measurement_id in ("herschel_bulkley",):
        n_se = next((m.se for m in result.metrics if m.name == "Flow index n"), None)
        n = value("Flow index n")
        if n_se and n and math.isfinite(n_se) and abs(n_se / n) > 0.2:
            flags.append(("warning", "Flow index uncertainty exceeds 20 %: the fit is poorly constrained."))
    elif measurement_id == "crossover":
        if not math.isfinite(value("Flow point (G′ = G″)", float("nan")) or float("nan")):
            flags.append(("info", "G′ and G″ do not cross within the sweep."))
    return flags
