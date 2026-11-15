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
from typing import Any, Mapping, Sequence

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


# Dimensions whose values cannot be negative whatever the equation says (Codex review,
# finding 4: a negative bulk density used to stay in the Monte Carlo distribution).
NON_NEGATIVE = frozenset({
    "length", "area", "second_moment", "volume", "mass", "density", "concentration",
    "thermal_conductivity", "thermal_diffusivity", "diffusion_coefficient", "effusivity",
    "specific_heat", "thermal_resistance", "specific_surface", "specific_volume", "viscosity",
    "shear_rate", "frequency", "time", "velocity", "flow_rate", "wavevector", "surface_tension",
    "cycles", "count_density", "linear_density", "bending_rigidity", "modulus", "pressure",
})
ABSOLUTE_ZERO_C = -273.15

# Relations between inputs that the formula itself does not enforce.
DOMAIN_RULES: dict[str, tuple] = {
    "porosity_from_density": (lambda v: v["rho_b"] <= v["rho_s"], "bulk density ≤ skeletal density"),
    "pore_volume": (lambda v: v["rho_b"] <= v["rho_s"], "bulk density ≤ skeletal density"),
    "relative_density": (lambda v: v["rho_b"] <= v["rho_s"], "bulk density ≤ skeletal density"),
    "k_model_aerogel_fibre": (lambda v: v["rho_b"] <= v["rho_s"], "bulk density ≤ skeletal density"),
    "density_scaling_modulus": (lambda v: v["rho"] <= v["rho_s"], "density ≤ solid density"),
    "density_scaling_crosslinked": (lambda v: v["rho"] <= v["rho_s"], "density ≤ solid density"),
    "elastic_recovery": (lambda v: v["PS"] <= v["eps_max"], "permanent set ≤ maximum strain"),
    "gel_content": (lambda v: v["W_gel"] <= v["W_0"], "insoluble mass ≤ initial mass"),
    "crystallinity_xrd": (lambda v: v["A_cryst"] <= v["A_total"], "crystalline area ≤ total area"),
    "ratcheting_strain": (lambda v: v["eps_min"] <= v["eps_max"], "minimum ≤ maximum strain"),
}


def lower_bound(var) -> float | None:
    """Declared minimum, or the physical one implied by the variable's dimension."""
    bounds = [b for b in (var.minimum,
                          0.0 if var.dimension in NON_NEGATIVE else None,
                          ABSOLUTE_ZERO_C if var.dimension == "temperature" and var.unit == "°C" else None)
              if b is not None]
    return max(bounds) if bounds else None


def domain_mask(eq: Equation, values: Mapping[str, Any]) -> np.ndarray:
    """True where every input is inside its physical bounds and the equation's relations hold.

    Works on scalars and on arrays of draws alike."""
    mask = np.array(True)
    for var in eq.inputs:
        if var.vector or var.symbol not in values:
            continue
        x = np.asarray(values[var.symbol], float)
        lo = lower_bound(var)
        if lo is not None:
            mask = mask & (x >= lo)
        if var.maximum is not None:
            mask = mask & (x <= var.maximum)
    rule = DOMAIN_RULES.get(eq.id)
    if rule is not None:
        mask = mask & np.asarray(rule[0]({k: np.asarray(v, float) if not isinstance(v, (list, tuple)) else v
                                          for k, v in values.items()}), bool)
    return mask


def check_domain(eq: Equation, values: Mapping[str, Any]) -> None:
    """Raise ValueError when the nominal values themselves are physically impossible."""
    if not bool(np.all(domain_mask(eq, values))):
        bad = []
        for v in eq.inputs:
            if v.vector or v.symbol not in values:
                continue
            x, lo = float(values[v.symbol]), lower_bound(v)
            if (lo is not None and x < lo) or (v.maximum is not None and x > v.maximum):
                bad.append(v.symbol)
        rule = DOMAIN_RULES.get(eq.id)
        why = f"outside physical bounds: {', '.join(bad)}" if bad else f"violates {rule[1]}" if rule else "outside the domain"
        raise ValueError(f"{eq.id}: nominal values {why}")


def _active(values: Mapping[str, float], sigmas: Mapping[str, float]) -> list[str]:
    return [k for k, s in sigmas.items() if s and k in values and not isinstance(values[k], (list, tuple))]


def propagate_linear(eq: Equation, values: Mapping[str, float], sigmas: Mapping[str, float],
                     correlations: Mapping | None = None) -> LinearResult:
    """First-order propagation with an optional correlation matrix."""
    check_domain(eq, values)
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
    check_domain(eq, values)
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
    # Draws outside the physical bounds or the equation's relations are rejected, not kept.
    ok = np.isfinite(out) & np.broadcast_to(
        domain_mask(eq, {**fixed, **{k: draws[:, i] for i, k in enumerate(names)}}), (n,))
    used = out[ok]
    if used.size < 0.5 * n:
        raise ValueError(f"more than half of the Monte Carlo draws ({n - used.size} of {n}) fell outside "
                         "the equation's domain — the uncertainties are too large for this point")
    lo, med, hi = np.percentile(used, [2.5, 50.0, 97.5])
    return MonteCarloResult(float(used.mean()), float(used.std(ddof=1)), float(med), float(lo), float(hi),
                            n, int(used.size), seed, used)


def compare(linear: LinearResult, mc: MonteCarloResult, tolerance: float = 0.1) -> dict:
    """Does the linear σ describe the Monte Carlo spread? Returns flags and a sentence."""
    out = {"agree": False, "status": "", "sd_ratio": float("nan"), "bias": float("nan"),
           "asymmetry": float("nan"), "message": ""}
    # Codex review, finding 5: a failed or zero linear estimate is never "agreement".
    if not math.isfinite(linear.sigma):
        out.update(status="unavailable",
                   message="The linear estimate is unavailable at this point (a derivative failed); "
                           f"use the Monte Carlo 95 % interval {mc.low:.4g} – {mc.high:.4g}.")
        return out
    if linear.sigma == 0 and mc.sd > 0:
        out.update(status="disagree",
                   message="The linear estimate is zero but the Monte Carlo spread is not (a stationary point "
                           f"or a nonlinear response): report the Monte Carlo 95 % interval {mc.low:.4g} – {mc.high:.4g}.")
        return out
    if linear.sigma == 0 and mc.sd == 0:
        out.update(agree=True, status="exact", message="No input uncertainty: both methods give an exact value.")
        return out
    if mc.sd == 0:
        out.update(status="disagree", message="The Monte Carlo spread is zero but the linear estimate is not.")
        return out
    ratio = mc.sd / linear.sigma
    bias = (mc.mean - linear.value) / linear.sigma
    up, down = mc.high - mc.median, mc.median - mc.low
    asym = (up - down) / (up + down) if (up + down) > 0 else 0.0
    agree = abs(ratio - 1.0) <= tolerance and abs(bias) <= tolerance and abs(asym) <= tolerance
    out.update(agree=agree, status="agree" if agree else "disagree", sd_ratio=ratio, bias=bias, asymmetry=asym)
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
