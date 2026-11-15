"""Mechanics studio: model comparisons and sensitivity checks on top of the curve analysers.

* `modulus_sensitivity`: how much Young's modulus moves when the fit window moves. A
  modulus that changes by 20 % between neighbouring windows is not a material constant.
* `compare_sn_models`: Basquin (log–log) against Wöhler (semi-log) S–N lines, both fitted
  as log life on stress (ASTM E739), compared by AIC, with bootstrap percentile intervals.
* `strain_life_bootstrap`: bootstrap intervals for b, c, σ′f/E and ε′f.
* `fit_relaxation` / `fit_creep`: linear-viscoelastic models (Maxwell, standard linear
  solid, two-term Prony, power law; Kelvin–Voigt, SLS, Burgers, Findley power law),
  compared by AIC and BIC.

Every result states the model's assumptions. Fitted curves are drawn only over the
calibration range: nothing here extrapolates.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np
from scipy import optimize, stats

from .curves import AnalysisResult, Metric, _clean_xy, _life_on_stress, _r2

__all__ = ["modulus_sensitivity", "compare_sn_models", "strain_life_bootstrap", "fit_relaxation",
           "fit_creep", "ModelFit", "RELAXATION_MODELS", "CREEP_MODELS", "VISCO_ASSUMPTIONS",
           "analyze_relaxation", "analyze_creep"]

VISCO_ASSUMPTIONS = ("Linear viscoelasticity (response proportional to the step), a step applied "
                     "instantaneously at t = 0, constant temperature and humidity, small strain. "
                     "Parameters describe the tested time window only.")


# ---------------------------------------------------------------------------
# modulus window sensitivity
# ---------------------------------------------------------------------------
def modulus_sensitivity(strain_pct: Sequence[float], stress_mpa: Sequence[float], *,
                        starts: Sequence[float] | None = None, widths: Sequence[float] | None = None,
                        min_points: int = 5) -> dict:
    """Least-squares modulus over a grid of windows (start, width in % strain).

    Returns the grid, every modulus, and the spread (min, max, coefficient of variation).
    By default the grid covers the first 40 % of the strain at UTS.
    """
    e, s = _clean_xy(strain_pct, stress_mpa, sort=True, name="modulus sensitivity")
    i_max = int(np.argmax(s))
    e_uts = float(e[i_max]) if e[i_max] > e[0] else float(e[-1])
    if starts is None:
        starts = np.linspace(e[0], e[0] + 0.2 * (e_uts - e[0]), 5)
    if widths is None:
        widths = np.linspace(0.05, 0.2, 4) * (e_uts - e[0])
    grid = []
    for lo in starts:
        for w in widths:
            hi = lo + w
            m = (e >= lo) & (e <= hi)
            if m.sum() < min_points:
                continue
            fit = stats.linregress(e[m] / 100.0, s[m])
            grid.append({"start": float(lo), "end": float(hi), "E": float(fit.slope),
                         "r2": float(fit.rvalue ** 2), "points": int(m.sum())})
    if not grid:
        raise ValueError("modulus sensitivity: no window holds enough points")
    moduli = np.array([g["E"] for g in grid])
    mean = float(moduli.mean())
    return {"windows": grid, "min": float(moduli.min()), "max": float(moduli.max()), "mean": mean,
            "cv_pct": float(moduli.std(ddof=1) / abs(mean) * 100.0) if moduli.size > 1 and mean else 0.0}


# ---------------------------------------------------------------------------
# S–N model comparison
# ---------------------------------------------------------------------------
def _aic(rss: float, n: int, k: int) -> float:
    return n * math.log(rss / n) + 2 * k if rss > 0 else -math.inf


def _fit_sn(two_n: np.ndarray, sa: np.ndarray, model: str) -> dict:
    y = np.log10(two_n)
    x = np.log10(sa) if model == "basquin" else sa
    fit = stats.linregress(x, y)
    rss = float(np.sum((y - (fit.intercept + fit.slope * x)) ** 2))
    if model == "basquin":
        b = 1.0 / fit.slope
        params = {"b": b, "sigma_f": 10.0 ** (-fit.intercept / fit.slope)}
    else:
        # log10(2N) = a + m·σ  ->  σ = (log10(2N) − a)/m = A + B·log10(2N)
        params = {"A": -fit.intercept / fit.slope, "B": 1.0 / fit.slope}
    return {"params": params, "rss": rss, "r2": float(fit.rvalue ** 2), "slope": float(fit.slope),
            "intercept": float(fit.intercept)}


def _predict_sn(model: str, params: dict, two_n: np.ndarray) -> np.ndarray:
    if model == "basquin":
        return params["sigma_f"] * two_n ** params["b"]
    return params["A"] + params["B"] * np.log10(two_n)


def compare_sn_models(cycles: Sequence[float], stress_amplitude: Sequence[float], *,
                      bootstrap: int = 1000, seed: int = 0) -> AnalysisResult:
    """Basquin versus Wöhler on the same data, with AIC weights and bootstrap intervals."""
    n_raw, sa = _clean_xy(cycles, stress_amplitude, sort=True, name="S-N comparison")
    if np.any(n_raw <= 0) or np.any(sa <= 0):
        raise ValueError("S-N comparison: cycles and amplitudes must be positive")
    if np.ptp(n_raw) <= 0 or np.ptp(sa) <= 0:
        raise ValueError("S-N comparison: lives (and amplitudes) must differ between specimens")
    two_n = 2.0 * n_raw
    n = two_n.size
    fits = {m: _fit_sn(two_n, sa, m) for m in ("basquin", "wohler")}
    aics = {m: _aic(f["rss"], n, 3) for m, f in fits.items()}       # slope, intercept, variance
    best = min(aics, key=aics.get)
    d = {m: aics[m] - aics[best] for m in aics}
    weights = {m: math.exp(-0.5 * d[m]) for m in d}
    total = sum(weights.values())
    weights = {m: w / total for m, w in weights.items()}

    rng = np.random.default_rng(seed)
    draws: dict[str, dict[str, list[float]]] = {m: {} for m in fits}
    for _ in range(int(bootstrap)):
        k = rng.integers(0, n, n)
        if np.ptp(sa[k]) <= 0 or np.ptp(two_n[k]) <= 0:
            continue
        for m in fits:
            try:
                p = _fit_sn(two_n[k], sa[k], m)["params"]
            except (ValueError, ZeroDivisionError, FloatingPointError):
                continue
            for key, v in p.items():
                if math.isfinite(v):
                    draws[m].setdefault(key, []).append(v)

    metrics: list[Metric] = []
    grid = np.logspace(np.log10(two_n.min()), np.log10(two_n.max()), 160)    # calibration range only
    curves: dict[str, tuple[np.ndarray, np.ndarray]] = {"data": (two_n, sa)}
    labels = {"basquin": "Basquin σa = σ′f(2N)^b", "wohler": "Wöhler σa = A + B·log₁₀(2N)"}
    units = {"b": "-", "sigma_f": "MPa", "A": "MPa", "B": "MPa/decade"}
    intervals = {}
    for m, f in fits.items():
        for key, value in f["params"].items():
            vals = draws[m].get(key, [])
            if len(vals) >= 50:
                lo, hi = (float(q) for q in np.percentile(vals, [2.5, 97.5]))
                note = f"bootstrap 95 % {lo:.4g} – {hi:.4g} ({len(vals)} resamples)"
                intervals[(m, key)] = (lo, hi)
            else:
                note = "too few specimens for a bootstrap interval"
            metrics.append(Metric(f"{labels[m].split()[0]} {key}", float(value), units[key], note))
        metrics.append(Metric(f"{labels[m].split()[0]} AIC", aics[m], "-",
                              f"Akaike weight {weights[m]:.2f}; R² of log life {f['r2']:.4f}"))
        curves[labels[m]] = (grid, _predict_sn(m, f["params"], grid))
    verdict = (f"{labels[best].split()[0]} is preferred (ΔAIC = {abs(d['basquin'] - d['wohler']):.2f})"
               if abs(d["basquin"] - d["wohler"]) >= 2 else "the two models fit about equally well (ΔAIC < 2)")
    metrics.append(Metric("Preferred S–N model", 1.0 if best == "basquin" else 2.0, "-",
                          f"1 = Basquin, 2 = Wöhler; {verdict}. Both regress log life on stress "
                          "(ASTM E739); lives outside the tested range are not predicted."))
    if n < 6:
        metrics.append(Metric("Specimens", float(n), "specimens",
                              "fewer than 6: model choice and intervals are weakly determined"))
    return AnalysisResult("sn_comparison", metrics, curves,
                          {"aic": aics, "weights": weights, "best": best, "fits": fits,
                           "intervals": intervals, "calibration_range": (float(two_n.min()), float(two_n.max()))})


def strain_life_bootstrap(cycles: Sequence[float], elastic: Sequence[float], plastic: Sequence[float], *,
                          bootstrap: int = 1000, seed: int = 0) -> dict[str, tuple[float, float, float]]:
    """{parameter: (estimate, low, high)} with bootstrap percentile 95 % intervals."""
    n = np.asarray(cycles, float)
    ea = np.asarray(elastic, float)
    pa = np.asarray(plastic, float)
    ok = np.isfinite(n) & np.isfinite(ea) & np.isfinite(pa) & (n > 0) & (ea > 0) & (pa > 0)
    n, ea, pa = n[ok], ea[ok], pa[ok]
    if n.size < 4:
        raise ValueError("strain-life bootstrap: need at least 4 specimens")
    two_n = 2.0 * n
    el, pl = _life_on_stress(two_n, ea), _life_on_stress(two_n, pa)
    est = {"b": el["exp"], "sigma_f/E": el["coef"], "c": pl["exp"], "eps_f": pl["coef"]}
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {k: [] for k in est}
    for _ in range(int(bootstrap)):
        k = rng.integers(0, n.size, n.size)
        if np.ptp(ea[k]) <= 0 or np.ptp(pa[k]) <= 0 or np.ptp(two_n[k]) <= 0:
            continue
        try:
            e2, p2 = _life_on_stress(two_n[k], ea[k]), _life_on_stress(two_n[k], pa[k])
        except ValueError:
            continue
        for key, v in (("b", e2["exp"]), ("sigma_f/E", e2["coef"]), ("c", p2["exp"]), ("eps_f", p2["coef"])):
            if math.isfinite(v):
                draws[key].append(v)
    out = {}
    for key, value in est.items():
        if len(draws[key]) >= 50:
            lo, hi = np.percentile(draws[key], [2.5, 97.5])
            out[key] = (float(value), float(lo), float(hi))
        else:
            out[key] = (float(value), float("nan"), float("nan"))
    return out


# ---------------------------------------------------------------------------
# viscoelastic models
# ---------------------------------------------------------------------------
@dataclass
class ModelFit:
    name: str
    params: dict[str, float]
    errors: dict[str, float]
    rss: float
    aic: float
    bic: float
    r2: float
    predict: Callable[[np.ndarray], np.ndarray] = field(repr=False)
    assumption: str = ""


def _model_table(kind: str):
    """name -> (function, parameter names, initial guess(t, y), bounds, assumption)."""
    if kind == "relaxation":
        return {
            "Maxwell": (lambda t, E0, tau: E0 * np.exp(-t / tau), ("E0", "tau"),
                        lambda t, y: [y[0], np.ptp(t) / 3 or 1.0], ([0, 1e-12], [np.inf, np.inf]),
                        "spring and dashpot in series: relaxes completely to zero"),
            "Standard linear solid": (lambda t, Einf, E1, tau: Einf + E1 * np.exp(-t / tau), ("E_inf", "E1", "tau"),
                                      lambda t, y: [y[-1], max(y[0] - y[-1], 1e-12), np.ptp(t) / 5 or 1.0],
                                      ([0, 0, 1e-12], [np.inf, np.inf, np.inf]),
                                      "Zener solid: one relaxation time, finite equilibrium modulus"),
            "Prony (2 terms)": (lambda t, Einf, E1, tau1, E2, tau2: Einf + E1 * np.exp(-t / tau1) + E2 * np.exp(-t / tau2),
                                ("E_inf", "E1", "tau1", "E2", "tau2"),
                                lambda t, y: [y[-1], max(y[0] - y[-1], 1e-12) / 2, np.ptp(t) / 50 or 0.1,
                                              max(y[0] - y[-1], 1e-12) / 2, np.ptp(t) / 3 or 1.0],
                                ([0, 0, 1e-12, 0, 1e-12], [np.inf] * 5),
                                "generalised Maxwell with two relaxation times"),
            "Power law (Nutting)": (lambda t, E1, n: E1 * np.power(np.clip(t, 1e-12, None), -n), ("E1", "n"),
                                    lambda t, y: [y[0], 0.1], ([0, 0], [np.inf, 1.0]),
                                    "self-similar relaxation, no single time constant; undefined at t = 0"),
        }
    return {
        "Kelvin–Voigt": (lambda t, Jinf, tau: Jinf * (1 - np.exp(-t / tau)), ("J_inf", "tau"),
                         lambda t, y: [y[-1], np.ptp(t) / 3 or 1.0], ([0, 1e-12], [np.inf, np.inf]),
                         "spring and dashpot in parallel: no instantaneous strain"),
        "Standard linear solid": (lambda t, J0, J1, tau: J0 + J1 * (1 - np.exp(-t / tau)), ("J0", "J1", "tau"),
                                  lambda t, y: [y[0], max(y[-1] - y[0], 1e-12), np.ptp(t) / 5 or 1.0],
                                  ([0, 0, 1e-12], [np.inf, np.inf, np.inf]),
                                  "instantaneous plus delayed elastic strain, bounded creep"),
        "Burgers": (lambda t, J0, J1, tau, eta_inv: J0 + J1 * (1 - np.exp(-t / tau)) + eta_inv * t,
                    ("J0", "J1", "tau", "1/eta"),
                    lambda t, y: [y[0], max(y[-1] - y[0], 1e-12) / 2, np.ptp(t) / 10 or 1.0,
                                  max(y[-1] - y[0], 1e-12) / (2 * (np.ptp(t) or 1.0))],
                    ([0, 0, 1e-12, 0], [np.inf] * 4),
                    "SLS plus a free dashpot: unbounded (steady-state) creep"),
        "Findley power law": (lambda t, J0, A, n: J0 + A * np.power(np.clip(t, 0, None), n), ("J0", "A", "n"),
                              lambda t, y: [y[0], max(y[-1] - y[0], 1e-12) / ((np.ptp(t) or 1.0) ** 0.3), 0.3],
                              ([0, 0, 1e-3], [np.inf, np.inf, 1.0]),
                              "empirical; common for polymer creep over a few decades"),
    }


RELAXATION_MODELS = tuple(_model_table("relaxation"))
CREEP_MODELS = tuple(_model_table("creep"))


def _fit_models(t: np.ndarray, y: np.ndarray, kind: str, models: Sequence[str] | None) -> list[ModelFit]:
    table = _model_table(kind)
    chosen = list(models) if models else list(table)
    n = t.size
    fits: list[ModelFit] = []
    for name in chosen:
        if name not in table:
            raise ValueError(f"unknown {kind} model {name!r}; choose from {', '.join(table)}")
        fn, pnames, guess, bounds, assumption = table[name]
        if n <= len(pnames) + 1:
            continue
        try:
            p0 = np.clip(np.asarray(guess(t, y), float), [b + 1e-15 for b in bounds[0]],
                         [b if np.isfinite(b) else 1e300 for b in bounds[1]])
            popt, pcov = optimize.curve_fit(fn, t, y, p0=p0, bounds=bounds, maxfev=40000)
        except (RuntimeError, ValueError, optimize.OptimizeWarning):
            continue
        pred = fn(t, *popt)
        rss = float(np.sum((y - pred) ** 2))
        k = len(pnames) + 1
        aic = n * math.log(max(rss, 1e-300) / n) + 2 * k
        bic = n * math.log(max(rss, 1e-300) / n) + k * math.log(n)
        with np.errstate(invalid="ignore"):
            perr = np.sqrt(np.clip(np.diag(pcov), 0, None)) if np.all(np.isfinite(pcov)) else np.full(len(popt), np.nan)
        fits.append(ModelFit(name, dict(zip(pnames, map(float, popt))), dict(zip(pnames, map(float, perr))),
                             rss, aic, bic, _r2(y, pred), (lambda tt, f=fn, p=popt: f(np.asarray(tt, float), *p)),
                             assumption))
    if not fits:
        raise ValueError(f"{kind}: no model could be fitted (too few points, or the curve has the wrong shape)")
    fits.sort(key=lambda f: f.aic)
    return fits


def fit_relaxation(time_s: Sequence[float], response: Sequence[float],
                   models: Sequence[str] | None = None) -> list[ModelFit]:
    t, y = _clean_xy(time_s, response, sort=True, name="relaxation")
    if np.any(t < 0):
        raise ValueError("relaxation: time must start at the step (t ≥ 0)")
    return _fit_models(t, y, "relaxation", models)


def fit_creep(time_s: Sequence[float], response: Sequence[float],
              models: Sequence[str] | None = None) -> list[ModelFit]:
    t, y = _clean_xy(time_s, response, sort=True, name="creep")
    if np.any(t < 0):
        raise ValueError("creep: time must start at the load step (t ≥ 0)")
    return _fit_models(t, y, "creep", models)


def _visco_result(kind: str, t: np.ndarray, y: np.ndarray, fits: list[ModelFit], y_unit: str,
                  y_label: str, note: str) -> AnalysisResult:
    best = fits[0]
    metrics = [Metric("Best model (lowest AIC)", 1.0, "-", f"{best.name}: {best.assumption}. {VISCO_ASSUMPTIONS}")]
    for pname, value in best.params.items():
        unit = "s" if pname.startswith("tau") else ("-" if pname == "n" else
                                                   (f"{y_unit}/s" if pname == "1/eta" else y_unit))
        err = best.errors.get(pname, float("nan"))
        metrics.append(Metric(f"{best.name}: {pname}", value, unit,
                              f"± {err:.3g} (1 SE)" if math.isfinite(err) else "SE unavailable", se=err))
    metrics.append(Metric(f"{best.name}: R²", best.r2, "-", note))
    for f in fits:
        metrics.append(Metric(f"AIC, {f.name}", f.aic, "-",
                              f"ΔAIC = {f.aic - best.aic:.2f}, BIC = {f.bic:.2f}, R² = {f.r2:.5f}"))
    grid = np.linspace(t.min(), t.max(), 300)                  # calibration window only
    curves = {"data": (t, y), "fit": (grid, best.predict(grid))}
    if len(fits) > 1:
        curves["runner-up fit"] = (grid, fits[1].predict(grid))
    return AnalysisResult(kind, metrics, curves,
                          {"fits": [{"name": f.name, "params": f.params, "errors": f.errors, "aic": f.aic,
                                     "bic": f.bic, "r2": f.r2, "assumption": f.assumption} for f in fits],
                           "calibration_range": (float(t.min()), float(t.max())), "y_label": y_label})


def analyze_relaxation(time_s: Sequence[float], stress_mpa: Sequence[float], *,
                       strain_pct: float | None = None, model: str = "auto") -> AnalysisResult:
    """Stress relaxation after a strain step. With `strain_pct`, fits the relaxation modulus."""
    t, s = _clean_xy(time_s, stress_mpa, sort=True, name="relaxation")
    y, unit, label = s, "MPa", "stress"
    if strain_pct:
        if strain_pct <= 0:
            raise ValueError("relaxation: the strain step must be positive")
        y, label = s / (strain_pct / 100.0), "relaxation modulus E(t)"
    fits = fit_relaxation(t, y, None if model in ("", "auto", None) else [model])
    return _visco_result("relaxation", t, y, fits, unit, label,
                         f"fitted to {label}" + (f" at a {strain_pct:g} % step" if strain_pct else ""))


def analyze_creep(time_s: Sequence[float], strain_pct: Sequence[float], *,
                  stress_mpa: float | None = None, model: str = "auto") -> AnalysisResult:
    """Creep under a constant stress. With `stress_mpa`, fits the creep compliance J(t)."""
    t, e = _clean_xy(time_s, strain_pct, sort=True, name="creep")
    y, unit, label = e, "%", "strain"
    if stress_mpa:
        if stress_mpa <= 0:
            raise ValueError("creep: the applied stress must be positive")
        y, unit, label = (e / 100.0) / stress_mpa, "1/MPa", "creep compliance J(t)"
    fits = fit_creep(t, y, None if model in ("", "auto", None) else [model])
    return _visco_result("creep", t, y, fits, unit, label,
                         f"fitted to {label}" + (f" at {stress_mpa:g} MPa" if stress_mpa else ""))
