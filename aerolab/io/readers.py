"""Import instrument data from whatever the lab actually produces.

Real exports are messy: an Instron file starts with twenty lines of metadata, a TA
Instruments text file puts units on a second header row, a European locale writes
"1,234", Origin writes Long Name / Units / Comments rows.  This module sniffs its way
through all of that and hands back a tidy `Dataset`.

Supported: .csv .tsv .txt .dat .asc .prn (delimited), .xlsx .xlsm .xls (sheets),
.json (records or column dicts), .npz, and the clipboard.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

__all__ = [
    "Dataset", "ImportError_", "read_any", "read_delimited", "read_excel", "read_json",
    "read_npz", "read_text", "sheet_names", "SUPPORTED_SUFFIXES", "file_filter",
]

SUPPORTED_SUFFIXES = {
    ".csv": "delimited", ".tsv": "delimited", ".txt": "delimited", ".dat": "delimited",
    ".asc": "delimited", ".prn": "delimited", ".curve": "delimited",
    ".xlsx": "excel", ".xlsm": "excel", ".xls": "excel",
    ".json": "json", ".npz": "npz",
}

_COMMENT_CHARS = ("#", "!", ";", "%", "//")
_NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?$")
_UNIT_ROW_RE = re.compile(r"^[\s\(\[]?[A-Za-zµΩ°%/·^\-\d\.\s\)\]\*]{0,24}$")


class ImportError_(Exception):
    """Raised when a file cannot be read as tabular data."""


@dataclass
class Dataset:
    """A tidy table: named columns of floats, plus whatever we learned on the way in."""
    name: str
    headers: list[str]
    columns: list[np.ndarray]
    units: list[str] = field(default_factory=list)
    source: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    text_columns: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.units:
            self.units = [""] * len(self.headers)
        if len(self.units) != len(self.headers):
            self.units = (self.units + [""] * len(self.headers))[:len(self.headers)]

    # -- access --------------------------------------------------------------
    @property
    def n_rows(self) -> int:
        return int(max((c.size for c in self.columns), default=0))

    @property
    def n_cols(self) -> int:
        return len(self.headers)

    def column(self, key: str | int) -> np.ndarray:
        if isinstance(key, int):
            return self.columns[key]
        for i, h in enumerate(self.headers):
            if h == key:
                return self.columns[i]
        low = key.strip().lower()
        for i, h in enumerate(self.headers):
            if h.strip().lower() == low:
                return self.columns[i]
        raise KeyError(f"{self.name}: no column named {key!r}")

    def label(self, index: int) -> str:
        unit = self.units[index] if index < len(self.units) else ""
        return f"{self.headers[index]} ({unit})" if unit else self.headers[index]

    def labels(self) -> list[str]:
        return [self.label(i) for i in range(self.n_cols)]

    def to_dict(self) -> dict[str, np.ndarray]:
        return {h: c for h, c in zip(self.headers, self.columns)}

    def subset(self, indices: Sequence[int], keys: Sequence[str] | None = None) -> dict[str, np.ndarray]:
        """Pull selected columns out, optionally renaming them to analyser keys."""
        keys = list(keys) if keys is not None else [self.headers[i] for i in indices]
        out: dict[str, np.ndarray] = {}
        for key, idx in zip(keys, indices):
            if idx is None:
                continue
            out[key] = self.columns[idx]
        return out

    def describe(self) -> list[dict[str, Any]]:
        rows = []
        for i, head in enumerate(self.headers):
            col = self.columns[i]
            finite = col[np.isfinite(col)]
            rows.append({
                "column": head, "unit": self.units[i], "n": int(col.size),
                "finite": int(finite.size),
                "min": float(finite.min()) if finite.size else math.nan,
                "max": float(finite.max()) if finite.size else math.nan,
                "mean": float(finite.mean()) if finite.size else math.nan,
            })
        return rows


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def read_any(path: str | Path, **kwargs: Any) -> list[Dataset]:
    """Read a file into one Dataset per sheet/table. Never returns an empty list."""
    p = Path(path)
    if not p.exists():
        raise ImportError_(f"File not found: {p}")
    kind = SUPPORTED_SUFFIXES.get(p.suffix.lower())
    if kind is None:
        kind = "excel" if p.suffix.lower().startswith(".xls") else "delimited"
    try:
        if kind == "excel":
            return read_excel(p, **kwargs)
        if kind == "json":
            return read_json(p, **kwargs)
        if kind == "npz":
            return read_npz(p, **kwargs)
        return [read_delimited(p, **kwargs)]
    except ImportError_:
        raise
    except Exception as exc:                                    # noqa: BLE001 - reported to the user
        raise ImportError_(f"{p.name}: {exc}") from exc


def file_filter() -> str:
    """Qt-style file dialog filter covering everything we can open."""
    return ("Data files (*.csv *.tsv *.txt *.dat *.asc *.prn *.xlsx *.xlsm *.xls *.json *.npz);;"
            "Delimited text (*.csv *.tsv *.txt *.dat *.asc *.prn);;"
            "Excel workbooks (*.xlsx *.xlsm *.xls);;JSON (*.json);;NumPy archive (*.npz);;"
            "All files (*)")


# ---------------------------------------------------------------------------
# delimited text
# ---------------------------------------------------------------------------
def read_text(text: str, name: str = "clipboard", **kwargs: Any) -> Dataset:
    """Parse delimited text already in memory (used by paste-from-clipboard)."""
    return _parse_delimited(text.splitlines(), name=name, source="", **kwargs)


def read_delimited(path: str | Path, encoding: str | None = None, **kwargs: Any) -> Dataset:
    p = Path(path)
    raw = p.read_bytes()
    text = _decode(raw, encoding)
    return _parse_delimited(text.splitlines(), name=p.stem, source=str(p), **kwargs)


def _decode(raw: bytes, encoding: str | None) -> str:
    if encoding:
        return raw.decode(encoding, errors="replace")
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _parse_delimited(lines: Sequence[str], name: str, source: str, *,
                     delimiter: str | None = None, decimal: str | None = None,
                     header_row: int | None = None, units_row: int | None = None,
                     skip_rows: int = 0) -> Dataset:
    lines = [ln.rstrip("\r\n") for ln in lines][skip_rows:]
    preamble: list[str] = []
    body: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not body and (not stripped or stripped.startswith(_COMMENT_CHARS)):
            if stripped:
                preamble.append(stripped.lstrip("#!;%/ "))
            continue
        body.append(line)
    if not body:
        raise ImportError_(f"{name}: no data rows found")

    if header_row is None and units_row is None:
        # Instrument exports often open with "Sample: X", "Date: ..." lines that carry no
        # comment character. Drop everything before the header of the main numeric block.
        start = _table_start(body, delimiter)
        preamble += [ln.strip() for ln in body[:start] if ln.strip()]
        body = body[start:]

    delimiter = delimiter or _sniff_delimiter(body)
    rows = _split_rows(body, delimiter)
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    width = _modal_width(rows)
    if delimiter == "whitespace" and rows and len(rows[0]) > width:
        rows[0] = _rejoin_units(rows[0], width)
    rows = [(r + [""] * width)[:width] for r in rows]

    decimal = decimal or _sniff_decimal(rows, delimiter)

    # Which leading rows are text?  The first is the header; a second all-text row that
    # looks like units (short, bracketed, no words) is the units row — Origin's own layout.
    if header_row is None:
        header_row = 0 if not _row_is_numeric(rows[0], decimal) else None
    if units_row is None and header_row is not None and len(rows) > header_row + 1:
        candidate = rows[header_row + 1]
        if not _row_is_numeric(candidate, decimal) and _looks_like_units(candidate):
            units_row = header_row + 1

    if header_row is None:
        headers = [f"Column {i + 1}" for i in range(width)]
        units = [""] * width
        first_data = 0
    else:
        headers = [c.strip() or f"Column {i + 1}" for i, c in enumerate(rows[header_row])]
        if units_row is not None:
            units = [c.strip().strip("()[]") for c in rows[units_row]]
            first_data = units_row + 1
        else:
            headers, units = _split_units(headers)
            first_data = header_row + 1
        # Origin writes Long Name / Units / Comments; skip any further text rows.
        while first_data < len(rows) and not _row_is_numeric(rows[first_data], decimal):
            first_data += 1

    data_rows = rows[first_data:]
    if not data_rows:
        raise ImportError_(f"{name}: header found but no numeric rows beneath it")

    columns, text_columns = _to_columns(data_rows, headers, decimal)
    meta = {"delimiter": delimiter, "decimal": decimal, "rows": len(data_rows)}
    if preamble:
        meta["preamble"] = preamble[:40]
    return Dataset(name=name, headers=headers, columns=columns, units=units,
                   source=source, meta=meta, text_columns=text_columns)


_MISSING_NUMBERS = {"nan", "inf", "infinity"}
_NUMBER_RE = re.compile(r"^[+-]?(\d[\d.,]*|[.,]\d+)([eEdD][+-]?\d+)?%?$")


def _numberish(line: str) -> int:
    """How many tokens on a line look like numbers (delimiter-agnostic)."""
    return sum(1 for t in re.split(r"[\s,;|]+", line.strip())
               if t and (_NUMBER_RE.match(t) or t.lower().lstrip("+-") in _MISSING_NUMBERS))


def _table_start(body: Sequence[str], delimiter: str | None) -> int:
    """Index of the first header line of the main table (or its first data line if none).

    The data block is the first run of >= 3 consecutive lines with >= 2 numbers each (or
    the rest of the file if shorter). Above it, consecutive text lines with as many fields
    as a data line are the header block (Origin writes Long Name / Units / Comments). If
    there are none, the single text line just above is taken as the header. Anything
    earlier is preamble ("Sample: X", "Date: ...").
    """
    n = len(body)
    data = 0
    for i in range(n):
        run = body[i:i + 3]
        if all(_numberish(ln) >= 2 for ln in run) and (len(run) == 3 or i + len(run) == n):
            data = i
            break
    else:
        return 0
    if data == 0:
        return 0
    # Sniff with the line above included: "30,000<TAB>99,99" alone reads as comma-separated.
    delim = delimiter or _sniff_delimiter(body[data - 1:data + 60])
    width = len(_split_rows([body[data]], delim)[0])

    def fields(line: str) -> int:
        return len(_split_rows([line], delim)[0])

    top = data
    while top > 0 and body[top - 1].strip() and _numberish(body[top - 1]) < 2 and (
            fields(body[top - 1]) == width
            or (delim == "whitespace" and fields(body[top - 1]) >= width)):
        top -= 1
    if top == data and body[data - 1].strip() and _numberish(body[data - 1]) < 2:
        top = data - 1
    return top


def _rejoin_units(tokens: Sequence[str], width: int) -> list[str]:
    """Whitespace header "Temperature (°C) Weight (%)" -> ["Temperature (°C)", "Weight (%)"]."""
    out: list[str] = []
    for tok in tokens:
        if out and (tok.startswith(("(", "[")) or out[-1].count("(") > out[-1].count(")")
                    or out[-1].count("[") > out[-1].count("]")):
            out[-1] = f"{out[-1]} {tok}"
        else:
            out.append(tok)
    return out if len(out) == width else list(tokens)


def _split_rows(body: Sequence[str], delimiter: str) -> list[list[str]]:
    if delimiter == "whitespace":
        return [re.split(r"\s+", ln.strip()) for ln in body]
    reader = csv.reader(io.StringIO("\n".join(body)), delimiter=delimiter,
                        skipinitialspace=True)
    return [list(r) for r in reader]


def _sniff_delimiter(body: Sequence[str]) -> str:
    sample = "\n".join(body[:60])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass
    best, best_score = "whitespace", 0.0
    for cand in (",", "\t", ";", "|"):
        counts = [ln.count(cand) for ln in body[:60] if ln.strip()]
        if not counts or max(counts) == 0:
            continue
        modal = max(set(counts), key=counts.count)
        score = modal * (counts.count(modal) / len(counts))
        if modal and score > best_score:
            best, best_score = cand, score
    return best


def _sniff_decimal(rows: Sequence[Sequence[str]], delimiter: str) -> str:
    """Tell '1,5' (European decimal) apart from a thousands separator."""
    if delimiter == ",":
        return "."
    comma_dec = dot_dec = 0
    for row in rows[:200]:
        for cell in row:
            c = cell.strip()
            if not c:
                continue
            if re.fullmatch(r"[+-]?\d+,\d+", c):
                comma_dec += 1
            elif re.fullmatch(r"[+-]?\d+\.\d+", c):
                dot_dec += 1
    return "," if comma_dec > dot_dec else "."


def _modal_width(rows: Sequence[Sequence[str]]) -> int:
    widths = [len(r) for r in rows if any(c.strip() for c in r)]
    if not widths:
        raise ImportError_("no usable rows")
    return max(set(widths), key=widths.count)


def _to_float(cell: str, decimal: str) -> float:
    c = cell.strip().strip('"')
    if not c or c.lower() in {"nan", "na", "n/a", "-", "--", "null", "none", "inf%"}:
        return math.nan
    if decimal == ",":
        # "1.234,5" -> 1234.5, but a lone point ("1.5e-3") is a decimal point, not grouping
        if re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+(,\d*)?", c):
            c = c.replace(".", "")
        c = c.replace(",", ".")
    elif "," in c:
        # Only true thousands grouping ("12,345.6") is stripped; "1,5" in a point-decimal
        # file is ambiguous and is left unparsed rather than read as 15.
        if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d*)?", c):
            c = c.replace(",", "")
    if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)[dD][+-]?\d+", c):
        c = c.replace("D", "E").replace("d", "e")       # Fortran exponent
    if c.endswith("%"):
        c = c[:-1]
    try:
        return float(c)
    except ValueError:
        return math.nan


def _row_is_numeric(row: Sequence[str], decimal: str) -> bool:
    """A data row: every cell parses as a number, bar at most one label column.

    The single allowance is what makes "NFT-1, 0.157" a data row while "Sample, Density"
    stays a header — a ratio test instead would reject a two-column file whose first
    column holds the sample name.
    """
    cells = [c for c in row if c.strip()]
    if not cells:
        return False
    good = sum(1 for c in cells if not math.isnan(_to_float(c, decimal)))
    return good >= max(1, len(cells) - 1)


def _looks_like_units(row: Sequence[str]) -> bool:
    cells = [c.strip() for c in row if c.strip()]
    if not cells:
        return True                     # a blank second row is a units row with no units
    if any(len(c) > 24 for c in cells):
        return False
    wordy = sum(1 for c in cells if len(c.split()) > 2)
    return wordy == 0 and all(_UNIT_ROW_RE.match(c) for c in cells)


def _split_units(headers: Sequence[str]) -> tuple[list[str], list[str]]:
    """Pull "Stress (MPa)" apart into name and unit — including nested "k (mW/(m·K))"."""
    names, units = [], []
    for h in headers:
        name, unit = _split_one_unit(h.strip())
        names.append(name)
        units.append(unit)
    return names, units


def _split_one_unit(header: str) -> tuple[str, str]:
    """Split off a trailing bracketed group, matching brackets so nesting survives."""
    if not header or header[-1] not in ")]":
        return header, ""
    close, open_ = header[-1], "(" if header[-1] == ")" else "["
    depth = 0
    for i in range(len(header) - 1, -1, -1):
        if header[i] == close:
            depth += 1
        elif header[i] == open_:
            depth -= 1
            if depth == 0:
                name, unit = header[:i].strip(), header[i + 1:-1].strip()
                if name and 0 < len(unit) <= 24:
                    return name, unit
                return header, ""
    return header, ""


def _to_columns(rows: Sequence[Sequence[str]], headers: Sequence[str],
                decimal: str) -> tuple[list[np.ndarray], dict[str, list[str]]]:
    width = len(headers)
    columns: list[np.ndarray] = []
    text_columns: dict[str, list[str]] = {}
    for j in range(width):
        cells = [row[j] if j < len(row) else "" for row in rows]
        values = np.array([_to_float(c, decimal) for c in cells], dtype=float)
        if np.isnan(values).all() and any(c.strip() for c in cells):
            text_columns[headers[j]] = [c.strip() for c in cells]
        columns.append(values)
    return columns, text_columns


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def sheet_names(path: str | Path) -> list[str]:
    import openpyxl
    wb = openpyxl.load_workbook(Path(path), read_only=True, data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def _excel_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)                              # full precision, always "." decimal
    return str(value)


def read_excel(path: str | Path, sheet: str | int | None = None, **kwargs: Any) -> list[Dataset]:
    """Read one sheet, or every sheet that holds numbers when `sheet` is None."""
    import openpyxl

    p = Path(path)
    if p.suffix.lower() == ".xls":
        raise ImportError_(f"{p.name}: the old binary .xls format cannot be read. Open it in "
                           "Excel or LibreOffice and save it as .xlsx (or .csv), then import that.")
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    try:
        if sheet is None:
            wanted = list(wb.sheetnames)
        elif isinstance(sheet, int):
            wanted = [wb.sheetnames[sheet]]
        else:
            wanted = [sheet]
        out: list[Dataset] = []
        for sheet_name in wanted:
            ws = wb[sheet_name]
            if not hasattr(ws, "iter_rows"):              # a chartsheet holds no cells
                continue
            grid = [[_excel_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
            grid = [r for r in grid if any(str(c).strip() for c in r)]
            if len(grid) < 2:
                continue
            width = _modal_width(grid)
            grid = [(r + [""] * width)[:width] for r in grid]
            try:
                ds = _parse_grid(grid, name=f"{p.stem} · {sheet_name}", source=str(p),
                                 **{"decimal": ".", **kwargs})
            except ImportError_:
                continue
            ds.meta["sheet"] = sheet_name
            out.append(ds)
        if not out:
            raise ImportError_(f"{p.name}: no sheet contained a numeric table")
        return out
    finally:
        wb.close()


def _parse_grid(grid: Sequence[Sequence[str]], name: str, source: str, **kwargs: Any) -> Dataset:
    text = "\n".join("\t".join(str(c).replace("\t", " ") for c in row) for row in grid)
    return _parse_delimited(text.splitlines(), name=name, source=source,
                            delimiter="\t", **kwargs)


# ---------------------------------------------------------------------------
# JSON / NPZ
# ---------------------------------------------------------------------------
def read_json(path: str | Path, **_kwargs: Any) -> list[Dataset]:
    """Accepts a list of records, a dict of columns, or an AeroLab export."""
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))

    if isinstance(payload, dict) and isinstance(payload.get("datasets"), list):
        out = []
        for i, block in enumerate(payload["datasets"]):
            out.append(_dataset_from_mapping(block.get("columns", block),
                                             block.get("name", f"{p.stem} {i + 1}"), str(p),
                                             block.get("units")))
        if out:
            return out

    if isinstance(payload, list):
        if not payload or not isinstance(payload[0], dict):
            raise ImportError_(f"{p.name}: expected a list of objects")
        headers = list(dict.fromkeys(k for rec in payload for k in rec))
        cols = {h: [rec.get(h) for rec in payload] for h in headers}
        return [_dataset_from_mapping(cols, p.stem, str(p), None)]

    if isinstance(payload, dict):
        return [_dataset_from_mapping(payload, p.stem, str(p), None)]

    raise ImportError_(f"{p.name}: unsupported JSON layout")


def _dataset_from_mapping(mapping: dict[str, Any], name: str, source: str,
                          units: Sequence[str] | None) -> Dataset:
    headers, columns, text_columns = [], [], {}
    for key, values in mapping.items():
        if not isinstance(values, (list, tuple)):
            continue
        headers.append(str(key))
        arr = np.array([_coerce(v) for v in values], dtype=float)
        columns.append(arr)
        if np.isnan(arr).all() and any(v is not None for v in values):
            text_columns[str(key)] = [str(v) for v in values]
    if not headers:
        raise ImportError_(f"{name}: no array-valued keys")
    names, split_units = _split_units(headers)
    return Dataset(name=name, headers=names, columns=columns,
                   units=list(units) if units else split_units, source=source,
                   meta={"format": "json"}, text_columns=text_columns)


def _coerce(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return math.nan
    if isinstance(value, (int, float)):
        return float(value)
    return _to_float(str(value), ".")


def read_npz(path: str | Path, **_kwargs: Any) -> list[Dataset]:
    p = Path(path)
    with np.load(p, allow_pickle=False) as archive:
        headers = list(archive.files)
        columns = [np.asarray(archive[k], dtype=float).ravel() for k in headers]
    if not headers:
        raise ImportError_(f"{p.name}: archive is empty")
    names, units = _split_units(headers)
    return [Dataset(name=p.stem, headers=names, columns=columns, units=units,
                    source=str(p), meta={"format": "npz"})]
