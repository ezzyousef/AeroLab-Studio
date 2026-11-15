"""Uncertainty propagation for the equation library: linear with covariance, and Monte Carlo.

`Equation.compute_with_uncertainty` (first order, independent inputs) stays the default.
This module adds what it leaves out:

* **Correlated inputs.** σ_f² = Jᵀ Σ J with Σ = D R D (D = diag σ, R = correlation
  matrix). The correlation matrix is optional; omitted pairs are uncorrelated. A matrix
  that is not symmetric, has |r| > 1 or is not positive semi-definite is refused, since no
  set of real measurements can produce it.
* **Monte Carlo cross-check.** Inputs are drawn from a multivariate normal distribution
  with the same means and covariance, and pushed through the exact equation. When the
  function curves noticeably over ±σ (1/x with a large σ, a power law, a value next to a
  domain limit) the linear σ and the Monte Carlo spread disagree, and the comparison
  says so. The Monte Carlo interval is then the one to report.

Assumptions, stated wherever results are shown: inputs are normally distributed with the
given 1σ; correlations are linear (Pearson); draws that fall outside the equation's
domain (a negative density, say) are discarded and counted, not clipped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .equations import Equation

__all__ = ["LinearResult", "MonteCarloResult", "check_correlation", "correlation_matrix",
           "propagate_linear", "monte_carlo", "compare", "ASSUMPTIONS"]

ASSUMPTIONS = ("Inputs normally distributed with the stated 1σ; correlations linear (Pearson). "
               "Linear propagation uses first derivatives at the nominal point (GUM, JCGM 100:2008 §5); "
               "Monte Carlo draws the same distribution through the exact equation (JCGM 101:2008).")


@dataclass
class LinearResult:
    value: float
    sigma: float
    gradient: dict[str, float]
    contributions: dict[str, float]          # share of the variance from each input (sums to ~1)
    correlated: bool
    note: str = ""


@dataclass
class MonteCarloResult:
    mean: float
    sd: float
    median: float
    low: float                                # 2.5th percentile
    high: float                               # 97.5th percentile
    n_requested: int
    n_used: int
    seed: int
    samples: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))

    @property
    def rejected_fraction(self) -> float:
        return 1.0 - self.n_used / self.n_requested if self.n_requested else float("nan")


def correlation_matrix(names: Sequence[str], pairs: Mapping | None) -> np.ndarray:
    """Build R from {(a, b): r} or {"a|b": r}; unspecified pairs are 0, the diagonal 1."""
    n = len(names)
    R = np.eye(n)
    index = {name: i for i, name in enumerate(names)}
    for key, r in (pairs or {}).items():
        a, b = key.split("|") if isinstance(key, str) else key
        if a not in index or b not in index:
            continue                          # a pair for an input with no σ plays no part
        if a == b:
            raise ValueError(f"correlation of {a} with itself is always 1")
        i, j = index[a], index[b]
        R[i, j] = R[j, i] = float(r)
    return R


def check_correlation(R: np.ndarray, names: Sequence[str] = ()) -> None:
    """Raise ValueError unless R is a valid correlation matrix."""
    R = np.asarray(R, float)
    if R.ndim != 2 or R.shape[0] != R.shape[1]:
        raise ValueError("the correlation matrix must be square")
    if not np.all(np.isfinite(R)):
        raise ValueError("the correlation matrix contains a non-number")
    if not np.allclose(R, R.T, atol=1e-12):
        raise ValueError("the correlation matrix must be symmetric")
    if not np.allclose(np.diag(R), 1.0, atol=1e-12):
        raise ValueError("the diagonal of a correlation matrix must be 1")
    if np.any(np.abs(R) > 1.0 + 1e-12):
        bad = np.argwhere(np.abs(R) > 1.0 + 1e-12)[0]
        label = f" ({names[bad[0]]}, {names[bad[1]]})" if names else ""
        raise ValueError(f"a correlation must lie between −1 and 1{label}")
    smallest = float(np.linalg.eigvalsh(R).min())
    if smallest < -1e-9:
        raise ValueError("these correlations cannot all hold at once (the matrix is not positive "
                         f"semi-definite; smallest eigenvalue {smallest:.3g}). Check their signs.")


def _active(values: Mapping[str, float], sigmas: Mapping[str, float]) -> list[str]:
    return [k for k, s in sigmas.items() if s and k in values and not isinstance(values[k], (list, tuple))]


def propagate_linear(eq: Equation, values: Mapping[str, float], sigmas: Mapping[str, float],
                     correlations: Mapping | None = None) -> LinearResult:
    """First-order propagation with an optional correlation matrix."""
    base = float(eq.compute(**values))
    names = _active(values, sigmas)
    if not names:
        return LinearResult(base, 0.0, {}, {}, False, "no input has an uncertainty")
    s = np.array([abs(float(sigmas[k])) for k in names])
    grad = np.empty(len(names))
    for i, k in enumerate(names):
        x = float(values[k])
        step = abs(x) * 1e-5 if x else 1e-8
        grad[i] = eq._derivative(dict(values), k, x, step, base)
    R = correlation_matrix(names, correlations)
    check_correlation(R, names)
    correlated = bool(np.any(np.abs(R - np.eye(len(names))) > 0))
    if not np.all(np.isfinite(grad)):
        return LinearResult(base, float("nan"), dict(zip(names, grad.tolist())), {}, correlated,
                            "a derivative could not be evaluated at this point")
    cov = np.outer(s, s) * R
    var = float(grad @ cov @ grad)
    var = max(var, 0.0)                         # rounding can leave −1e-30 for an exact cancel
    contrib: dict[str, float] = {}
    if var > 0:
        # Share of each input including its covariance terms (row sums of the quadratic form)
        shares = grad * (cov @ grad) / var
        contrib = dict(zip(names, shares.tolist()))
    return LinearResult(base, math.sqrt(var), dict(zip(names, grad.tolist())), contrib, correlated)


def monte_carlo(eq: Equation, values: Mapping[str, float], sigmas: Mapping[str, float],
                correlations: Mapping | None = None, n: int = 20000, seed: int = 0) -> MonteCarloResult:
    """Propagate by sampling. Reproducible for a given seed."""
    if n < 100:
        raise ValueError("Monte Carlo needs at least 100 draws")
    names = _active(values, sigmas)
    if not names:
        v = float(eq.compute(**values))
        return MonteCarloResult(v, 0.0, v, v, v, n, n, seed, np.full(1, v))
    mu = np.array([float(values[k]) for k in names])
    s = np.array([abs(float(sigmas[k])) for k in names])
    R = correlation_matrix(names, correlations)
    check_correlation(R, names)
    # Eigen-decomposition rather than Cholesky, so a correlation of exactly ±1 (singular R)
    # still samples correctly.
    w, V = np.linalg.eigh(R)
    L = V * np.sqrt(np.clip(w, 0.0, None))
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n, len(names)))
    draws = mu + (z @ L.T) * s
    fixed = {k: v for k, v in values.items() if k not in names}
    out = np.empty(n)
    with np.errstate(all="ignore"):
        try:
            # every equation is vectorised over numpy arrays
            out = np.asarray(eq.compute(**fixed, **{k: draws[:, i] for i, k in enumerate(names)}), float)
            if out.shape != (n,):
                raise ValueError
        except Exception:                       # noqa: BLE001 - fall back to one draw at a time
            for j in range(n):
                try:
                    out[j] = float(eq.compute(**fixed, **{k: float(draws[j, i]) for i, k in enumerate(names)}))
                except Exception:               # noqa: BLE001 - outside the domain
                    out[j] = np.nan
    # Inputs declared non-negative (a density, a length) that were drawn negative are
    # outside the model, so those draws are rejected as well as non-finite outputs.
    ok = np.isfinite(out)
    for i, k in enumerate(names):
        var = next((v for v in eq.inputs if v.symbol == k), None)
        if var is not None and var.minimum is not None:
            ok &= draws[:, i] >= var.minimum
        if var is not None and var.maximum is not None:
            ok &= draws[:, i] <= var.maximum
    used = out[ok]
    if used.size < 0.5 * n:
        raise ValueError(f"more than half of the Monte Carlo draws ({n - used.size} of {n}) fell outside "
                         "the equation's domain — the uncertainties are too large for this point")
    lo, med, hi = np.percentile(used, [2.5, 50.0, 97.5])
    return MonteCarloResult(float(used.mean()), float(used.std(ddof=1)), float(med), float(lo), float(hi),
                            n, int(used.size), seed, used)


def compare(linear: LinearResult, mc: MonteCarloResult, tolerance: float = 0.1) -> dict:
    """Does the linear σ describe the Monte Carlo spread? Returns flags and a sentence."""
    out = {"agree": True, "sd_ratio": float("nan"), "bias": float("nan"), "asymmetry": float("nan"),
           "message": ""}
    if not (math.isfinite(linear.sigma) and linear.sigma > 0 and mc.sd > 0):
        out["message"] = "nothing to compare (zero or unavailable uncertainty)"
        return out
    ratio = mc.sd / linear.sigma
    bias = (mc.mean - linear.value) / linear.sigma
    up, down = mc.high - mc.median, mc.median - mc.low
    asym = (up - down) / (up + down) if (up + down) > 0 else 0.0
    agree = abs(ratio - 1.0) <= tolerance and abs(bias) <= tolerance and abs(asym) <= tolerance
    out.update(agree=agree, sd_ratio=ratio, bias=bias, asymmetry=asym)
    if agree:
        out["message"] = (f"Monte Carlo agrees with the linear estimate (SD ratio {ratio:.3f}); "
                          "the ± value is a fair 1σ.")
    else:
        out["message"] = (f"Monte Carlo disagrees with the linear estimate (SD ratio {ratio:.2f}, mean shifted "
                          f"{bias:+.2f}σ, interval asymmetry {asym:+.2f}). The function is not linear over ±σ: "
                          f"report the Monte Carlo 95 % interval {mc.low:.4g} – {mc.high:.4g} instead.")
    if mc.rejected_fraction > 0:
        out["message"] += f" {mc.rejected_fraction * 100:.1f} % of draws fell outside the domain and were discarded."
    return out
