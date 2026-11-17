"""Experiment explorer: batch comparison, response surfaces, sensitivity, dimensional analysis,
design-of-experiments suggestions and export verification.

Nothing here invents a measurement. A design of experiments returns the *settings* to
run, with empty result columns. A response surface is fitted only to results the user
has, and drawn only over the box those results span.
"""
from __future__ import annotations

import csv
import io
import itertools
import math
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import stats

from .equations import Equation
from .units import SI_SIGNATURE

__all__ = ["group_statistics", "welch_t_test", "one_way_anova", "normalised_comparison",
           "response_surface", "elasticities", "dimensional_analysis", "doe_design", "DOE_KINDS",
           "verify_excel_export", "verify_origin_package"]


# ---------------------------------------------------------------------------
# batches
# ---------------------------------------------------------------------------
def group_statistics(values_by_group: Mapping[str, Sequence[float]]) -> dict[str, dict[str, float]]:
    from .workspace import replicate_statistics
    return {g: replicate_statistics(v) for g, v in values_by_group.items()}


def welch_t_test(a: Sequence[float], b: Sequence[float]) -> dict[str, float]:
    """Two-sided Welch t-test (unequal variances). NaN when either group has < 2 values."""
    a = np.asarray([x for x in a if x is not None and math.isfinite(x)], float)
    b = np.asarray([x for x in b if x is not None and math.isfinite(x)], float)
    if a.size < 2 or b.size < 2:
        return {"t": float("nan"), "df": float("nan"), "p": float("nan"), "diff": float("nan")}
    va, vb = a.var(ddof=1) / a.size, b.var(ddof=1) / b.size
    if va + vb == 0:
        return {"t": float("nan"), "df": float("nan"), "p": float("nan"), "diff": float(a.mean() - b.mean())}
    t = (a.mean() - b.mean()) / math.sqrt(va + vb)
    df = (va + vb) ** 2 / (va ** 2 / (a.size - 1) + vb ** 2 / (b.size - 1))
    p = 2 * stats.t.sf(abs(t), df)
    return {"t": float(t), "df": float(df), "p": float(p), "diff": float(a.mean() - b.mean())}


def one_way_anova(values_by_group: Mapping[str, Sequence[float]]) -> dict[str, float]:
    groups = [np.asarray([x for x in v if x is not None and math.isfinite(x)], float)
              for v in values_by_group.values()]
    groups = [g for g in groups if g.size >= 2]
    if len(groups) < 2:
        return {"F": float("nan"), "p": float("nan"), "groups": float(len(groups))}
    F, p = stats.f_oneway(*groups)
    return {"F": float(F), "p": float(p), "groups": float(len(groups))}


def normalised_comparison(rows: Sequence[Mapping[str, Any]], reference: str) -> list[dict[str, Any]]:
    """Each row {sample, value, density?} → value/reference value and value/density.

    The specific value (per density) is the fair comparison between aerogels of different
    density. It is left blank when the density is unknown, never guessed.
    """
    ref = next((r for r in rows if r["sample"] == reference), None)
    if ref is None or not ref.get("value") or not math.isfinite(ref["value"]):
        raise ValueError(f"reference {reference!r} has no value")
    ref_density = ref.get("density")
    ref_specific = ref["value"] / ref_density if ref_density else None
    out = []
    for r in rows:
        v, rho = r.get("value"), r.get("density")
        specific = v / rho if (v is not None and rho) else float("nan")
        out.append({"sample": r["sample"], "value": v, "relative": v / ref["value"] if v is not None else float("nan"),
                    "density": rho if rho else float("nan"), "specific": specific,
                    "specific_relative": specific / ref_specific if ref_specific and math.isfinite(specific)
                    else float("nan")})
    return out


# ---------------------------------------------------------------------------
# response surface
# ---------------------------------------------------------------------------
_RS_TERMS = ("1", "x1", "x2", "x1²", "x2²", "x1·x2")


def response_surface(x1: Sequence[float], x2: Sequence[float], y: Sequence[float], *,
                     names: tuple[str, str] = ("x1", "x2")) -> dict[str, Any]:
    """Full quadratic in two factors by least squares, with coefficient SEs.

    Needs at least 7 distinct runs (6 coefficients plus one degree of freedom). The
    prediction grid covers the box spanned by the data only, and the stationary point is
    reported with whether it lies inside that box.
    """
    a = np.asarray(x1, float)
    b = np.asarray(x2, float)
    yy = np.asarray(y, float)
    ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(yy)
    a, b, yy = a[ok], b[ok], yy[ok]
    n = yy.size
    if n < 7:
        raise ValueError(f"response surface: {n} runs; a quadratic in two factors needs at least 7")
    X = np.column_stack([np.ones(n), a, b, a ** 2, b ** 2, a * b])
    if np.linalg.matrix_rank(X) < 6:
        raise ValueError("response surface: the runs do not span both factors at three or more levels")
    coef, *_ = np.linalg.lstsq(X, yy, rcond=None)
    pred = X @ coef
    rss = float(np.sum((yy - pred) ** 2))
    dof = n - 6
    sigma2 = rss / dof if dof > 0 else float("nan")
    cov = sigma2 * np.linalg.inv(X.T @ X) if dof > 0 else np.full((6, 6), np.nan)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    ss_tot = float(np.sum((yy - yy.mean()) ** 2))
    r2 = 1 - rss / ss_tot if ss_tot > 0 else float("nan")
    adj = 1 - (1 - r2) * (n - 1) / dof if dof > 0 and math.isfinite(r2) else float("nan")
    b0, b1, b2, b11, b22, b12 = coef
    H = np.array([[2 * b11, b12], [b12, 2 * b22]])
    stationary, kind, inside = None, "none", False
    if abs(np.linalg.det(H)) > 1e-12:
        xs = np.linalg.solve(H, -np.array([b1, b2]))
        eig = np.linalg.eigvalsh(H)
        kind = "minimum" if np.all(eig > 0) else "maximum" if np.all(eig < 0) else "saddle"
        inside = bool(a.min() <= xs[0] <= a.max() and b.min() <= xs[1] <= b.max())
        stationary = (float(xs[0]), float(xs[1]), float(np.array([1, xs[0], xs[1], xs[0] ** 2, xs[1] ** 2,
                                                                   xs[0] * xs[1]]) @ coef))
    g1 = np.linspace(a.min(), a.max(), 40)
    g2 = np.linspace(b.min(), b.max(), 40)
    G1, G2 = np.meshgrid(g1, g2)
    Z = b0 + b1 * G1 + b2 * G2 + b11 * G1 ** 2 + b22 * G2 ** 2 + b12 * G1 * G2
    return {"coefficients": dict(zip(_RS_TERMS, map(float, coef))), "se": dict(zip(_RS_TERMS, map(float, se))),
            "r2": r2, "adj_r2": adj, "dof": dof, "rss": rss, "names": names,
            "stationary": stationary, "stationary_kind": kind, "stationary_inside": inside,
            "grid": (G1, G2, Z), "box": ((float(a.min()), float(a.max())), (float(b.min()), float(b.max())))}


# ---------------------------------------------------------------------------
# sensitivity and dimensional analysis of an equation
# ---------------------------------------------------------------------------
def elasticities(eq: Equation, values: Mapping[str, float]) -> dict[str, float]:
    """Local elasticity ∂ln y/∂ln xᵢ: the % change in the result per 1 % change in each input.

    Inputs at zero (where a relative change is undefined) or list-valued inputs are skipped.
    """
    base = float(eq.compute(**values))
    out = {}
    for var in eq.inputs:
        x = values.get(var.symbol)
        if isinstance(x, (list, tuple)) or x is None or float(x) == 0 or base == 0:
            continue
        x = float(x)
        step = abs(x) * 1e-6
        d = eq._derivative(dict(values), var.symbol, x, step, base)
        out[var.symbol] = float(d * x / base) if math.isfinite(d) else float("nan")
    return out


def _null_space_rational(M: np.ndarray) -> list[list[Fraction]]:
    """Integer-friendly null-space basis of a small rational matrix (Gauss–Jordan in Fractions)."""
    rows, cols = M.shape
    A = [[Fraction(M[i, j]).limit_denominator(1000) for j in range(cols)] for i in range(rows)]
    pivots, r = [], 0
    for c in range(cols):
        pr = next((i for i in range(r, rows) if A[i][c] != 0), None)
        if pr is None:
            continue
        A[r], A[pr] = A[pr], A[r]
        piv = A[r][c]
        A[r] = [v / piv for v in A[r]]
        for i in range(rows):
            if i != r and A[i][c] != 0:
                f = A[i][c]
                A[i] = [vi - f * vr for vi, vr in zip(A[i], A[r])]
        pivots.append(c)
        r += 1
        if r == rows:
            break
    free = [c for c in range(cols) if c not in pivots]
    basis = []
    for f in free:
        vec = [Fraction(0)] * cols
        vec[f] = Fraction(1)
        for i, p in enumerate(pivots):
            vec[p] = -A[i][f]
        # scale to the smallest integers
        denom = math.lcm(*[v.denominator for v in vec]) if vec else 1
        ints = [v * denom for v in vec]
        g = math.gcd(*[int(v) for v in ints if v != 0]) or 1
        basis.append([Fraction(int(v), g) for v in ints])
    return basis


def dimensional_analysis(eq: Equation) -> dict[str, Any]:
    """Buckingham π analysis of an equation's inputs (and output) from SI base dimensions.

    Returns each variable's signature, the rank of the dimension matrix, the number of
    independent dimensionless groups (variables − rank), and a basis for those groups as
    exponent vectors. Variables whose dimension depends on a fitted exponent (Pa·sⁿ) are
    listed as excluded.
    """
    variables, excluded = [], []
    for var in (*eq.inputs, eq.output):
        sig = SI_SIGNATURE.get(var.dimension)
        if sig is None or var.vector:
            excluded.append(var.symbol)
            continue
        variables.append((var.symbol, sig))
    base = ("M", "L", "T", "Θ")
    M = np.array([[float(sig[d]) for _s, sig in variables] for d in base]) if variables else np.zeros((4, 0))
    rank = int(np.linalg.matrix_rank(M)) if variables else 0
    basis = _null_space_rational(M) if variables else []
    groups = []
    for vec in basis:
        terms = [(variables[i][0], e) for i, e in enumerate(vec) if e != 0]
        groups.append({"exponents": {s: str(e) for s, e in terms},
                       "expression": " · ".join(f"{s}^{e}" if e != 1 else s for s, e in terms)})
    return {"variables": {s: {d: str(sig[d]) for d in base if sig[d]} for s, sig in variables},
            "rank": rank, "n_groups": len(variables) - rank, "groups": groups, "excluded": excluded}


# ---------------------------------------------------------------------------
# design of experiments (suggestions only)
# ---------------------------------------------------------------------------
DOE_KINDS = ("2-level full factorial", "3-level full factorial", "central composite (face-centred)",
             "Latin hypercube")


def doe_design(factors: Mapping[str, tuple[float, float]], kind: str = "2-level full factorial", *,
               runs: int | None = None, center_points: int = 0, seed: int = 0,
               randomise: bool = True) -> dict[str, Any]:
    """Settings to run, with coded levels. No responses are produced or implied.

    `factors` maps a name to (low, high). The run order is randomised (seeded) unless
    `randomise` is False, as good practice against drift.
    """
    names = list(factors)
    if not names:
        raise ValueError("DOE: add at least one factor")
    for name, (lo, hi) in factors.items():
        if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
            raise ValueError(f"DOE: factor {name!r} needs low < high")
    k = len(names)
    if kind == "2-level full factorial":
        coded = [list(p) for p in itertools.product([-1.0, 1.0], repeat=k)]
    elif kind == "3-level full factorial":
        coded = [list(p) for p in itertools.product([-1.0, 0.0, 1.0], repeat=k)]
    elif kind == "central composite (face-centred)":
        coded = [list(p) for p in itertools.product([-1.0, 1.0], repeat=k)]
        for i in range(k):
            for s in (-1.0, 1.0):
                pt = [0.0] * k
                pt[i] = s
                coded.append(pt)
        coded.append([0.0] * k)
    elif kind == "Latin hypercube":
        n = int(runs or max(2 * k + 1, 8))
        rng = np.random.default_rng(seed)
        cols = [(rng.permutation(n) + rng.random(n)) / n * 2 - 1 for _ in range(k)]
        coded = [[float(c[i]) for c in cols] for i in range(n)]
    else:
        raise ValueError(f"DOE: unknown design {kind!r}; choose from {', '.join(DOE_KINDS)}")
    coded += [[0.0] * k for _ in range(max(0, center_points))]
    if len(coded) > 500:
        raise ValueError(f"DOE: {len(coded)} runs is too many; use fewer factors or a Latin hypercube")
    order = list(range(len(coded)))
    if randomise:
        np.random.default_rng(seed).shuffle(order)
    rows = []
    for run_no, idx in enumerate(order, start=1):
        c = coded[idx]
        actual = {n: factors[n][0] + (v + 1) / 2 * (factors[n][1] - factors[n][0]) for n, v in zip(names, c)}
        rows.append({"run": run_no, "standard order": idx + 1, **{f"{n} (coded)": v for n, v in zip(names, c)},
                     **actual, "result": None})
    return {"kind": kind, "factors": dict(factors), "runs": rows, "seed": seed,
            "note": "Suggested settings only. Fill in the result column from real measurements; "
                    "no response is generated or assumed."}


# ---------------------------------------------------------------------------
# export verification
# ---------------------------------------------------------------------------
def _same(a: Any, b: float, rel: float) -> bool:
    if b is None or (isinstance(b, float) and not math.isfinite(b)):
        # the workbook writes a missing value as the text "n/a" (or an Excel error code)
        return (a is None or (isinstance(a, str) and (a == "n/a" or a.startswith("#")))
                or (isinstance(a, float) and not math.isfinite(a)))
    try:
        a = float(a)
    except (TypeError, ValueError):
        return False
    return math.isclose(a, float(b), rel_tol=rel, abs_tol=1e-300)


def verify_excel_export(path: str | Path, runs: Sequence[tuple[str, str, Sequence]], *,
                        rel: float = 1e-12) -> dict[str, Any]:
    """Read the written workbook back and compare every Summary value with the session.

    `runs` is [(sample, measurement name, metrics)], metrics having .name and .value.
    """
    import openpyxl
    wb = openpyxl.load_workbook(Path(path), read_only=True, data_only=True)
    try:
        ws = wb["Summary"]
        found = {}
        for row in ws.iter_rows(min_row=6, values_only=True):
            if not row or row[0] is None:
                continue
            found.setdefault((str(row[0]), str(row[1]), str(row[2])), []).append(row[3])
    finally:
        wb.close()
    checked, mismatches = 0, []
    for sample, mname, metrics in runs:
        for m in metrics:
            values = found.get((sample, mname, m.name))
            checked += 1
            if not values:
                mismatches.append(f"{sample} · {mname} · {m.name}: missing from the workbook")
            elif not any(_same(v, m.value, rel) for v in values):
                mismatches.append(f"{sample} · {mname} · {m.name}: workbook {values[0]!r} ≠ session {m.value!r}")
    return {"checked": checked, "mismatches": mismatches, "ok": not mismatches}


def verify_origin_package(folder: str | Path, items: Sequence[Any], *, rel: float = 1e-9) -> dict[str, Any]:
    """Re-read every CSV of a LabTalk package and compare its columns with the run curves."""
    folder = Path(folder)
    checked, mismatches = 0, []
    for item in items:
        path = folder / "data" / f"{item.safe_id}.csv"
        if not path.exists():
            mismatches.append(f"{item.safe_id}.csv is missing")
            continue
        rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))[3:]
        col = 0
        for key, (x, y) in item.result.curves.items():
            x = np.asarray(x, float).ravel()
            y = np.asarray(y, float).ravel()
            n = min(x.size, y.size)
            if n == 0:
                continue
            for arr in (x[:n], y[:n]):
                got = [r[col] if col < len(r) else "" for r in rows][:n]
                for i, (g, v) in enumerate(zip(got, arr)):
                    checked += 1
                    if not math.isfinite(v):
                        if g != "":
                            mismatches.append(f"{item.safe_id} {key} row {i + 1}: expected blank for NaN")
                    elif g == "" or not math.isclose(float(g), float(v), rel_tol=rel, abs_tol=1e-300):
                        mismatches.append(f"{item.safe_id} {key} row {i + 1}: {g!r} ≠ {v!r}")
                        if len(mismatches) > 50:
                            return {"checked": checked, "mismatches": mismatches, "ok": False}
                col += 1
    return {"checked": checked, "mismatches": mismatches, "ok": not mismatches}
