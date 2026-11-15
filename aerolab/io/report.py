"""Publishable summary report: results with units and assumptions, equations, provenance, sources.

`build_report()` gathers everything into a plain dict. `write_html()` and `write_markdown()`
render it. The HTML is self-contained, with no scripts and no external resources, so it
can be archived next to the data or attached to a manuscript submission. Every value
from a file (sample names, notes) is HTML-escaped.
"""
from __future__ import annotations

import hashlib
import html
import math
import platform
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

__all__ = ["build_report", "write_html", "write_markdown"]


def _sha256(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return "file not available"


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if not math.isfinite(v):
            return "n/a"
        return f"{v:.6g}"
    return str(v)


def build_report(*, project: str, author: str, runs: Sequence[Any], manual: Sequence[Any] = (),
                 workspace=None, validation: Sequence[Any] = (), notebook: Sequence[Any] = (),
                 qc: dict | None = None) -> dict[str, Any]:
    """`runs` are Run-like objects (sample, measurement, result, source, options, key)."""
    import numpy
    import scipy

    from .. import __version__
    from ..core import equations as E

    qc = qc or {}
    run_blocks = []
    for r in runs:
        exp = workspace.experiment_for_run(r.key) if workspace is not None else None
        run_blocks.append({
            "title": f"{r.sample} · {r.measurement.name}",
            "method": r.measurement.summary, "reference": r.measurement.reference,
            "source": r.source, "sha256": _sha256(r.source) if r.source else "",
            "options": {k: v for k, v in (r.options or {}).items() if v is not None},
            "metrics": [{"name": m.name, "value": m.value, "unit": m.unit, "note": m.note,
                         "se": getattr(m, "se", None)} for m in r.result.metrics],
            "experiment": None if exp is None else {
                "id": exp.experiment_id, "sample": exp.sample_id, "instrument": exp.instrument.name,
                "model": exp.instrument.model, "serial": exp.instrument.serial,
                "calibration": exp.instrument.calibration_date or "not recorded", "operator": exp.operator},
            "qc": qc.get(r.key, []),
        })
    used = sorted({c.equation_id for c in manual if c.equation_id in E.REGISTRY})
    equations = [{"id": i, "name": E.get(i).name, "latex": E.get(i).latex, "reference": E.get(i).reference,
                  "notes": E.get(i).notes} for i in used]
    samples = []
    if workspace is not None:
        for s in workspace.samples.values():
            try:
                derived = s.derived()
            except Exception:                              # noqa: BLE001 - incomplete record
                derived = {}
            samples.append({"id": s.sample_id, "name": s.name, "batch": s.batch, "replicate_of": s.replicate_of,
                            "components": [(c.name, c.mass_fraction, c.density_g_cm3) for c in s.components],
                            "process": s.process, "thermal_history": s.thermal_history, "derived": derived})
    attachments = [] if workspace is None else [
        {"name": a.name, "sha256": a.sha256, "kind": a.kind, "linked": a.experiment_id or a.sample_id}
        for a in workspace.attachments.values()]
    return {
        "project": project, "author": author, "generated": datetime.now().isoformat(timespec="seconds"),
        "software": {"AeroLab Studio": __version__, "Python": platform.python_version(),
                     "NumPy": numpy.__version__, "SciPy": scipy.__version__},
        "runs": run_blocks,
        "manual": [{"name": c.name, "inputs": c.input_text(), "value": c.value, "unit": c.unit,
                    "sigma": c.uncertainty, "method": c.uncertainty_method(), "reference": c.reference}
                   for c in manual],
        "equations": equations, "samples": samples, "attachments": attachments,
        "validation": [{"name": v.case.name, "value": v.value, "expected": v.case.expected, "ok": v.ok,
                        "basis": v.case.basis, "source": v.case.source, "comment": v.case.comment}
                       for v in validation],
        "notebook": [{"time": n.time, "author": n.author, "text": n.text, "links": list(n.links)} for n in notebook],
        "lineage": [] if workspace is None else [
            {"time": e.time, "action": e.action, "target": e.target, "detail": e.detail, "actor": e.actor}
            for e in workspace.lineage[-200:]],
    }


_CSS = """body{font-family:'Segoe UI',DejaVu Sans,Arial,sans-serif;max-width:1050px;margin:2em auto;padding:0 1em;
color:#141A22;line-height:1.45}h1{font-size:1.7em;margin-bottom:.1em}h2{border-bottom:2px solid #2E6FD9;
padding-bottom:.2em;margin-top:2em}h3{margin-bottom:.3em}table{border-collapse:collapse;width:100%;margin:.5em 0 1em}
th,td{border:1px solid #D5DBE3;padding:4px 7px;text-align:left;vertical-align:top;font-size:.92em}
th{background:#F1F4F8}td.num{text-align:right;font-variant-numeric:tabular-nums}.muted{color:#5D6672}
code{background:#F1F4F8;padding:1px 4px;border-radius:3px}.warn{color:#8A4B00}"""


def write_html(report: dict[str, Any], path: str | Path) -> Path:
    e = html.escape
    out: list[str] = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
                      f"<title>{e(report['project'])} — AeroLab report</title><style>{_CSS}</style></head><body>",
                      f"<h1>{e(report['project'])}</h1>",
                      f"<p class='muted'>{e(report['author'] or 'Author not set')} · generated {e(report['generated'])} · "
                      + " · ".join(f"{e(k)} {e(str(v))}" for k, v in report["software"].items()) + "</p>"]
    out.append("<h2>Results</h2>")
    if not report["runs"]:
        out.append("<p class='muted'>No analysed datasets.</p>")
    for r in report["runs"]:
        out.append(f"<h3>{e(r['title'])}</h3><p>{e(r['method'])}<br><span class='muted'>Method reference: "
                   f"{e(r['reference'] or '—')}</span></p>")
        prov = []
        if r["source"]:
            prov.append(f"source file <code>{e(Path(r['source']).name)}</code>, SHA-256 <code>{e(r['sha256'])}</code>")
        if r["options"]:
            prov.append("settings: " + ", ".join(f"{e(str(k))} = {e(_fmt(v))}" for k, v in r["options"].items()))
        if r["experiment"]:
            x = r["experiment"]
            prov.append(f"experiment {e(x['id'])} on sample {e(x['sample'])}; instrument {e(x['instrument'] or '—')} "
                        f"{e(x['model'])} {e(x['serial'])}, calibrated {e(x['calibration'])}; operator {e(x['operator'] or '—')}")
        if prov:
            out.append("<p class='muted'>" + "<br>".join(prov) + "</p>")
        out.append("<table><tr><th>Quantity</th><th>Value</th><th>± (1 SE)</th><th>Unit</th>"
                   "<th>Assumptions and notes</th></tr>")
        for m in r["metrics"]:
            out.append(f"<tr><td>{e(m['name'])}</td><td class='num'>{e(_fmt(m['value']))}</td>"
                       f"<td class='num'>{e(_fmt(m['se'])) if m['se'] is not None else ''}</td>"
                       f"<td>{e(m['unit'])}</td><td>{e(m['note'])}</td></tr>")
        out.append("</table>")
        if r["qc"]:
            out.append("<p class='warn'>QC: " + "<br>".join(e(msg) for _lvl, msg in r["qc"]) + "</p>")
    if report["manual"]:
        out.append("<h2>Calculations</h2><table><tr><th>Equation</th><th>Inputs</th><th>Result</th><th>±</th>"
                   "<th>Unit</th><th>Uncertainty method</th><th>Reference</th></tr>")
        for c in report["manual"]:
            out.append(f"<tr><td>{e(c['name'])}</td><td>{e(c['inputs'])}</td><td class='num'>{e(_fmt(c['value']))}</td>"
                       f"<td class='num'>{e(_fmt(c['sigma']))}</td><td>{e(c['unit'])}</td><td>{e(c['method'])}</td>"
                       f"<td>{e(c['reference'])}</td></tr>")
        out.append("</table>")
    if report["equations"]:
        out.append("<h2>Equations used</h2><table><tr><th>Equation</th><th>Formula (LaTeX)</th><th>Source</th><th>Notes</th></tr>")
        for q in report["equations"]:
            out.append(f"<tr><td>{e(q['name'])}</td><td><code>{e(q['latex'])}</code></td><td>{e(q['reference'])}</td>"
                       f"<td>{e(q['notes'])}</td></tr>")
        out.append("</table>")
    if report["samples"]:
        out.append("<h2>Samples</h2><table><tr><th>Sample</th><th>Composition (mass fraction, g/cm³)</th>"
                   "<th>Process</th><th>Thermal history</th><th>Derived</th></tr>")
        for s in report["samples"]:
            comp = "; ".join(f"{e(n)} {f:g}" + (f" ({d:g})" if d else "") for n, f, d in s["components"])
            proc = "; ".join(f"{e(k)}: {e(_fmt(v.get('value', v.get('text', ''))))} {e(v.get('unit', ''))}"
                             for k, v in s["process"].items())
            hist = "; ".join(e(str(h.get("step", ""))) for h in s["thermal_history"])
            der = "; ".join(f"{e(k)} {e(_fmt(v['value']))} {e(v['unit'])} ({e(v['source'])})" for k, v in s["derived"].items())
            rep = f" (replicate of {e(s['replicate_of'])})" if s["replicate_of"] else ""
            out.append(f"<tr><td>{e(s['id'])}{rep}<br>{e(s['name'])}</td><td>{comp}</td><td>{proc}</td>"
                       f"<td>{hist}</td><td>{der}</td></tr>")
        out.append("</table>")
    if report["validation"]:
        ok = sum(1 for v in report["validation"] if v["ok"])
        out.append(f"<h2>Equation-library validation</h2><p>{ok} of {len(report['validation'])} cases behave as "
                   "documented. Cases marked 'ours' are recomputations; two record disagreements with the papers.</p>"
                   "<table><tr><th>Case</th><th>Computed</th><th>Reference</th><th>Basis</th><th>Source</th></tr>")
        for v in report["validation"]:
            out.append(f"<tr><td>{e(v['name'])}</td><td class='num'>{e(_fmt(v['value']))}</td>"
                       f"<td class='num'>{e(_fmt(v['expected']))}</td><td>{e(v['basis'])}</td><td>{e(v['source'])}</td></tr>")
        out.append("</table>")
    if report["notebook"]:
        out.append("<h2>Notebook</h2>")
        for n in report["notebook"]:
            links = f" <span class='muted'>[{e(', '.join(n['links']))}]</span>" if n["links"] else ""
            out.append(f"<p><span class='muted'>{e(n['time'])} {e(n['author'])}</span>{links}<br>{e(n['text'])}</p>")
    out.append("<h2>Provenance</h2>")
    if report["attachments"]:
        out.append("<table><tr><th>Attached file</th><th>Kind</th><th>Linked to</th><th>SHA-256</th></tr>")
        for a in report["attachments"]:
            out.append(f"<tr><td>{e(a['name'])}</td><td>{e(a['kind'])}</td><td>{e(a['linked'])}</td>"
                       f"<td><code>{e(a['sha256'])}</code></td></tr>")
        out.append("</table>")
    if report["lineage"]:
        out.append("<table><tr><th>Time</th><th>Who</th><th>Action</th><th>Record</th><th>Detail</th></tr>")
        for ev in report["lineage"]:
            out.append(f"<tr><td>{e(ev['time'])}</td><td>{e(ev['actor'])}</td><td>{e(ev['action'])}</td>"
                       f"<td>{e(ev['target'])}</td><td>{e(ev['detail'])}</td></tr>")
        out.append("</table>")
    out.append("<p class='muted'>Values are as computed by AeroLab Studio from the files listed above. Model "
               "assumptions are stated next to each result; fitted curves were not extrapolated.</p></body></html>")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out), encoding="utf-8")
    return p


def write_markdown(report: dict[str, Any], path: str | Path) -> Path:
    def cell(v: Any) -> str:
        return _fmt(v).replace("|", "\\|").replace("\n", " ")

    lines = [f"# {report['project']}", "",
             f"{report['author'] or 'Author not set'} · generated {report['generated']} · "
             + " · ".join(f"{k} {v}" for k, v in report["software"].items()), "", "## Results", ""]
    for r in report["runs"]:
        lines += [f"### {r['title']}", "", r["method"], "", f"Method reference: {r['reference'] or '—'}", ""]
        if r["source"]:
            lines += [f"Source: `{Path(r['source']).name}` (SHA-256 `{r['sha256']}`)", ""]
        lines += ["| Quantity | Value | Unit | Assumptions and notes |", "|---|---:|---|---|"]
        lines += [f"| {cell(m['name'])} | {cell(m['value'])} | {cell(m['unit'])} | {cell(m['note'])} |"
                  for m in r["metrics"]]
        lines.append("")
        for _lvl, msg in r["qc"]:
            lines.append(f"- QC: {msg}")
        lines.append("")
    if report["equations"]:
        lines += ["## Equations used", ""]
        lines += [f"- **{q['name']}**: `{q['latex']}` — {q['reference']}" for q in report["equations"]]
        lines.append("")
    if report["attachments"]:
        lines += ["## Attached files", ""]
        lines += [f"- {a['name']} ({a['kind']}, {a['linked']}): `{a['sha256']}`" for a in report["attachments"]]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
