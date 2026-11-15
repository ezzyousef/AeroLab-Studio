"""The sample-to-experiment workspace: what was made, how it was made, and what was measured.

A `Workspace` holds

* **samples**: composition, production and spinning parameters, density, geometry,
  thermal history and replication (a replicate points at its parent sample);
* **experiments**: one measurement on one sample, with the instrument, its settings and
  calibration date, the operator, and the analysed runs it produced;
* **attachments**: raw-data files, images and documents, recorded by SHA-256 so a later
  change to the file on disk is detected;
* **lineage**: an append-only log of who did what to which record, and when. That log is
  the chain of custody: file → dataset → run → experiment → sample.

Everything here is plain data with no Qt, so it is unit-tested and scripted directly. It
is stored inside the session file (schema version 2). `migrate()` upgrades older session
files, and `export_archive()` / `import_archive()` write and read a portable `.aerolabz`
zip that carries the session together with every attached file.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import zipfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

__all__ = [
    "SCHEMA_VERSION", "Component", "Sample", "Instrument", "Experiment", "Attachment",
    "LineageEvent", "Workspace", "WorkspaceError", "migrate", "export_archive", "import_archive",
    "replicate_statistics", "sha256_file", "ARCHIVE_SUFFIX",
]

SCHEMA_VERSION = 2
ARCHIVE_SUFFIX = ".aerolabz"
MAX_ARCHIVE_MEMBER = 512 * 1024 * 1024        # one attached file
MAX_ARCHIVE_TOTAL = 2 * 1024 * 1024 * 1024    # everything, uncompressed
MAX_COMPRESSION_RATIO = 200                   # a zip bomb compresses far better than data
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}$")


class WorkspaceError(ValueError):
    """A workspace operation that would leave inconsistent or unsafe data."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------
@dataclass
class Component:
    name: str
    mass_fraction: float                      # 0–1 of the solid
    density_g_cm3: float | None = None
    supplier: str = ""
    lot: str = ""


@dataclass
class Sample:
    sample_id: str
    name: str = ""
    batch: str = ""
    formulation: str = ""
    components: list[Component] = field(default_factory=list)
    # free-form but unit-carrying: {"flow rate": {"value": 2.0, "unit": "mL/h"}, "bath": {"text": "ethanol"}}
    process: dict[str, dict[str, Any]] = field(default_factory=dict)
    bulk_density_g_cm3: float | None = None
    bulk_density_sigma: float | None = None
    skeletal_density_g_cm3: float | None = None
    geometry: dict[str, dict[str, Any]] = field(default_factory=dict)
    thermal_history: list[dict[str, Any]] = field(default_factory=list)   # steps, in order
    replicate_of: str = ""                    # parent sample id, for a replicate
    notes: str = ""
    created: str = field(default_factory=_now)

    def mass_fraction_total(self) -> float:
        return float(sum(c.mass_fraction for c in self.components))

    def derived(self) -> dict[str, dict[str, Any]]:
        """Values computed from what was entered, each with its formula as provenance."""
        from .equations import get

        out: dict[str, dict[str, Any]] = {}
        rho_s, rho_s_note = self.skeletal_density_g_cm3, "entered"
        dens = [c for c in self.components if c.density_g_cm3]
        if rho_s is None and self.components and len(dens) == len(self.components):
            rho_s = float(get("skeletal_density_mixture").compute(
                w=[c.mass_fraction for c in self.components], rho=[c.density_g_cm3 for c in self.components]))
            rho_s_note = "rule of mixtures over the components (skeletal_density_mixture)"
        if rho_s is not None:
            out["skeletal density"] = {"value": rho_s, "unit": "g/cm^3", "source": rho_s_note}
        if rho_s and self.bulk_density_g_cm3:
            eq = get("porosity_from_density")
            values = {"rho_b": self.bulk_density_g_cm3, "rho_s": rho_s}
            if self.bulk_density_sigma:
                value, sigma = eq.compute_with_uncertainty(values, {"rho_b": self.bulk_density_sigma})
            else:
                value, sigma = float(eq.compute(**values)), None
            out["porosity"] = {"value": float(value), "unit": "%", "sigma": sigma,
                               "source": "porosity_from_density (Omranpour et al. 2024a Eq. 1)"}
            out["pore volume"] = {"value": float(get("pore_volume").compute(**values)), "unit": "cm^3/g",
                                  "source": "pore_volume (Omranpour et al. 2024a Eq. 2)"}
        return out


@dataclass
class Instrument:
    name: str = ""
    model: str = ""
    serial: str = ""
    calibration_date: str = ""                # ISO date of the last calibration, "" if unknown
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class Experiment:
    experiment_id: str
    sample_id: str
    measurement_id: str
    instrument: Instrument = field(default_factory=Instrument)
    operator: str = ""
    date: str = ""
    run_keys: list[str] = field(default_factory=list)       # "dataset::measurement" of linked runs
    attachment_ids: list[str] = field(default_factory=list)
    notes: str = ""
    created: str = field(default_factory=_now)


@dataclass
class Attachment:
    attachment_id: str
    name: str
    path: str                                  # where the file is on this computer
    sha256: str
    size: int
    kind: str = "raw data"                    # raw data | image | document
    sample_id: str = ""
    experiment_id: str = ""
    added: str = field(default_factory=_now)

    @property
    def archive_name(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9._\-]+", "_", self.name)[:80] or "file"
        return f"attachments/{self.sha256[:12]}_{safe}"


@dataclass
class LineageEvent:
    time: str
    action: str
    target: str                                # "sample:S1", "experiment:E1", "attachment:A1", "run:..."
    detail: str = ""
    actor: str = ""


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
_DOC_SUFFIXES = {".pdf", ".docx", ".doc", ".md", ".txt", ".pptx"}


def _kind_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _DOC_SUFFIXES and suffix != ".txt":
        return "document"
    return "raw data"


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------
class Workspace:
    def __init__(self) -> None:
        self.samples: dict[str, Sample] = {}
        self.experiments: dict[str, Experiment] = {}
        self.attachments: dict[str, Attachment] = {}
        self.lineage: list[LineageEvent] = []
        self.actor: str = ""

    # -- lineage -------------------------------------------------------------
    def log(self, action: str, target: str, detail: str = "") -> None:
        self.lineage.append(LineageEvent(_now(), action, target, detail, self.actor))

    def history(self, target: str) -> list[LineageEvent]:
        """Events about one record, plus those about records linked to it."""
        targets = {target}
        kind, _, key = target.partition(":")
        if kind == "sample":
            targets |= {f"experiment:{e.experiment_id}" for e in self.experiments.values() if e.sample_id == key}
            targets |= {f"attachment:{a.attachment_id}" for a in self.attachments.values() if a.sample_id == key}
            for e in self.experiments.values():
                if e.sample_id == key:
                    targets |= {f"run:{k}" for k in e.run_keys}
                    targets |= {f"attachment:{a}" for a in e.attachment_ids}
        elif kind == "experiment" and key in self.experiments:
            targets |= {f"run:{k}" for k in self.experiments[key].run_keys}
            targets |= {f"attachment:{a}" for a in self.experiments[key].attachment_ids}
        return [ev for ev in self.lineage if ev.target in targets]

    # -- samples -------------------------------------------------------------
    def new_id(self, prefix: str, existing: Iterable[str]) -> str:
        taken = set(existing)
        n = len(taken) + 1
        while f"{prefix}{n}" in taken:
            n += 1
        return f"{prefix}{n}"

    def add_sample(self, sample: Sample) -> Sample:
        if not _ID_RE.match(sample.sample_id or ""):
            raise WorkspaceError("a sample id must start with a letter or digit and use letters, digits, "
                                 "spaces, '.', '_' or '-' (at most 64 characters)")
        if sample.sample_id in self.samples:
            raise WorkspaceError(f"there is already a sample {sample.sample_id!r}")
        self._check_sample(sample)
        self.samples[sample.sample_id] = sample
        self.log("sample created", f"sample:{sample.sample_id}",
                 f"replicate of {sample.replicate_of}" if sample.replicate_of else sample.name)
        return sample

    def _check_sample(self, sample: Sample) -> None:
        total = sample.mass_fraction_total()
        if sample.components and not (0.0 < total <= 1.0 + 1e-6):
            raise WorkspaceError(f"mass fractions must add up to at most 1 (they add up to {total:g}); "
                                 "enter fractions, not percentages")
        for c in sample.components:
            if c.mass_fraction < 0:
                raise WorkspaceError(f"{c.name}: a mass fraction cannot be negative")
            if c.density_g_cm3 is not None and c.density_g_cm3 <= 0:
                raise WorkspaceError(f"{c.name}: density must be positive")
        for name, value in (("bulk density", sample.bulk_density_g_cm3),
                            ("skeletal density", sample.skeletal_density_g_cm3)):
            if value is not None and not (math.isfinite(value) and value > 0):
                raise WorkspaceError(f"{name} must be a positive number")
        if (sample.bulk_density_g_cm3 and sample.skeletal_density_g_cm3
                and sample.bulk_density_g_cm3 > sample.skeletal_density_g_cm3):
            raise WorkspaceError("bulk density is larger than skeletal density, which would mean negative porosity")
        if sample.replicate_of and sample.replicate_of not in self.samples:
            raise WorkspaceError(f"replicate of unknown sample {sample.replicate_of!r}")
        if sample.replicate_of == sample.sample_id:
            raise WorkspaceError("a sample cannot be a replicate of itself")

    def update_sample(self, sample_id: str, **changes: Any) -> Sample:
        old = self.samples[sample_id]
        allowed = {f.name for f in fields(Sample)} - {"sample_id", "created"}
        unknown = set(changes) - allowed
        if unknown:
            raise WorkspaceError(f"unknown sample field(s): {', '.join(sorted(unknown))}")
        new = copy.deepcopy(old)
        for key, value in changes.items():
            setattr(new, key, value)
        self._check_sample(new)
        changed = [k for k in changes if getattr(old, k) != getattr(new, k)]
        self.samples[sample_id] = new
        if changed:
            self.log("sample edited", f"sample:{sample_id}", ", ".join(changed))
        return new

    def add_replicate(self, parent_id: str, sample_id: str | None = None) -> Sample:
        """A new sample with the parent's composition and process, marked as its replicate."""
        parent = self.samples[parent_id]
        root = parent.replicate_of or parent_id
        sid = sample_id or self.new_id(f"{root}-r", [s for s in self.samples if s.startswith(f"{root}-r")])
        rep = copy.deepcopy(parent)
        rep.sample_id, rep.replicate_of, rep.created = sid, root, _now()
        rep.bulk_density_g_cm3 = rep.bulk_density_sigma = None      # measured per specimen
        rep.notes = ""
        return self.add_sample(rep)

    def replicates(self, sample_id: str) -> list[Sample]:
        """The parent and every replicate of it, parent first."""
        root = self.samples[sample_id].replicate_of or sample_id
        group = [self.samples[root]] if root in self.samples else []
        group += [s for s in self.samples.values() if s.replicate_of == root]
        return group

    def remove_sample(self, sample_id: str) -> None:
        if any(e.sample_id == sample_id for e in self.experiments.values()):
            raise WorkspaceError("remove this sample's experiments first — their lineage would be orphaned")
        if any(s.replicate_of == sample_id for s in self.samples.values()):
            raise WorkspaceError("this sample has replicates; remove or re-parent them first")
        del self.samples[sample_id]
        self.log("sample removed", f"sample:{sample_id}")

    # -- experiments ----------------------------------------------------------
    def add_experiment(self, experiment: Experiment) -> Experiment:
        if experiment.sample_id not in self.samples:
            raise WorkspaceError(f"unknown sample {experiment.sample_id!r}")
        if experiment.experiment_id in self.experiments:
            raise WorkspaceError(f"there is already an experiment {experiment.experiment_id!r}")
        if not _ID_RE.match(experiment.experiment_id or ""):
            raise WorkspaceError("invalid experiment id")
        cal = experiment.instrument.calibration_date
        if cal:
            try:
                datetime.fromisoformat(cal)
            except ValueError as exc:
                raise WorkspaceError(f"calibration date {cal!r} is not an ISO date (YYYY-MM-DD)") from exc
        self.experiments[experiment.experiment_id] = experiment
        self.log("experiment created", f"experiment:{experiment.experiment_id}",
                 f"{experiment.measurement_id} on sample {experiment.sample_id}")
        return experiment

    def link_run(self, experiment_id: str, run_key: str) -> None:
        exp = self.experiments[experiment_id]
        if run_key not in exp.run_keys:
            exp.run_keys.append(run_key)
            self.log("run linked", f"run:{run_key}", f"to experiment {experiment_id}")

    def experiment_for_run(self, run_key: str) -> Experiment | None:
        return next((e for e in self.experiments.values() if run_key in e.run_keys), None)

    # -- attachments ----------------------------------------------------------
    def attach_file(self, path: str | Path, *, sample_id: str = "", experiment_id: str = "",
                    kind: str | None = None) -> Attachment:
        p = Path(path)
        if not p.is_file():
            raise WorkspaceError(f"not a file: {p}")
        if sample_id and sample_id not in self.samples:
            raise WorkspaceError(f"unknown sample {sample_id!r}")
        if experiment_id and experiment_id not in self.experiments:
            raise WorkspaceError(f"unknown experiment {experiment_id!r}")
        size = p.stat().st_size
        if size > MAX_ARCHIVE_MEMBER:
            raise WorkspaceError(f"{p.name} is larger than {MAX_ARCHIVE_MEMBER // 2**20} MB")
        digest = sha256_file(p)
        aid = self.new_id("A", self.attachments)
        att = Attachment(aid, p.name, str(p.resolve()), digest, size, kind or _kind_for(p),
                         sample_id, experiment_id)
        self.attachments[aid] = att
        if experiment_id:
            self.experiments[experiment_id].attachment_ids.append(aid)
        self.log("file attached", f"attachment:{aid}", f"{p.name} sha256 {digest[:16]}… ({size} bytes)")
        return att

    def verify_attachments(self) -> list[tuple[Attachment, str]]:
        """('ok' | 'missing' | 'changed') for every attachment; changes are logged."""
        out = []
        for att in self.attachments.values():
            p = Path(att.path)
            if not p.is_file():
                status = "missing"
            elif sha256_file(p) != att.sha256:
                status = "changed"
            else:
                status = "ok"
            if status != "ok":
                self.log(f"attachment {status}", f"attachment:{att.attachment_id}", att.path)
            out.append((att, status))
        return out

    def images_for(self, sample_id: str = "", experiment_id: str = "") -> list[Attachment]:
        """Images linked to a sample or experiment: the image ↔ mechanical-data link."""
        ids = set(self.experiments[experiment_id].attachment_ids) if experiment_id else set()
        return [a for a in self.attachments.values() if a.kind == "image"
                and ((sample_id and a.sample_id == sample_id) or a.attachment_id in ids)]

    # -- serialisation --------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": [asdict(s) for s in self.samples.values()],
            "experiments": [asdict(e) for e in self.experiments.values()],
            "attachments": [asdict(a) for a in self.attachments.values()],
            "lineage": [asdict(ev) for ev in self.lineage],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Workspace":
        ws = cls()
        data = data or {}
        for raw in data.get("samples", []):
            raw = dict(raw)
            raw["components"] = [Component(**_known(Component, c)) for c in raw.get("components", [])]
            s = Sample(**_known(Sample, raw))
            ws.samples[s.sample_id] = s
        for raw in data.get("experiments", []):
            raw = dict(raw)
            raw["instrument"] = Instrument(**_known(Instrument, raw.get("instrument") or {}))
            e = Experiment(**_known(Experiment, raw))
            ws.experiments[e.experiment_id] = e
        for raw in data.get("attachments", []):
            a = Attachment(**_known(Attachment, raw))
            ws.attachments[a.attachment_id] = a
        ws.lineage = [LineageEvent(**_known(LineageEvent, ev)) for ev in data.get("lineage", [])]
        return ws

    def copy(self) -> "Workspace":
        clone = Workspace.from_dict(copy.deepcopy(self.to_dict()))
        clone.actor = self.actor
        return clone

    def is_empty(self) -> bool:
        return not (self.samples or self.experiments or self.attachments)


def _known(cls, raw: dict[str, Any]) -> dict[str, Any]:
    """Drop keys a newer version may have added, so an older reader still opens the file."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in raw.items() if k in names}


# ---------------------------------------------------------------------------
# replication statistics
# ---------------------------------------------------------------------------
def replicate_statistics(values: Iterable[float]) -> dict[str, float]:
    """Mean, sample SD, standard error and the t-based 95 % interval of replicates."""
    from scipy import stats

    v = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    n = len(v)
    out = {"n": float(n), "mean": float("nan"), "sd": float("nan"), "se": float("nan"),
           "ci95_low": float("nan"), "ci95_high": float("nan"), "cv_pct": float("nan")}
    if n == 0:
        return out
    mean = sum(v) / n
    out["mean"] = mean
    if n >= 2:
        sd = math.sqrt(sum((x - mean) ** 2 for x in v) / (n - 1))
        se = sd / math.sqrt(n)
        t = float(stats.t.ppf(0.975, n - 1))
        out.update(sd=sd, se=se, ci95_low=mean - t * se, ci95_high=mean + t * se,
                   cv_pct=sd / abs(mean) * 100.0 if mean else float("nan"))
    return out


# ---------------------------------------------------------------------------
# migrations
# ---------------------------------------------------------------------------
def migrate(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Upgrade a session payload to the current schema. Returns (payload, notes).

    v1 (AeroLab ≤ 1.2): runs and kept calculations only.
    v2 (1.3): adds `workspace` (samples, experiments, attachments, lineage) and
              `notebook`, and records `schema_version`.
    A file from a newer version is refused rather than half-read.
    """
    if payload.get("format") != "aerolab-session":
        raise WorkspaceError("not an AeroLab session file")
    data = copy.deepcopy(payload)
    version = int(data.get("schema_version", data.get("version", 1)) or 1)
    notes: list[str] = []
    if version > SCHEMA_VERSION:
        raise WorkspaceError(f"this session was saved by a newer AeroLab (schema {version}); "
                             f"this version reads up to schema {SCHEMA_VERSION}")
    if version < 2:
        data.setdefault("workspace", Workspace().to_dict())
        data.setdefault("notebook", [])
        ws = data["workspace"]
        ws.setdefault("lineage", []).append(asdict(LineageEvent(
            _now(), "migrated", "session", f"schema {version} → 2 (workspace and notebook added)")))
        notes.append(f"Upgraded from schema {version} to 2: the session gained an empty workspace and notebook.")
        version = 2
    data["schema_version"] = version
    data["version"] = version
    return data, notes


# ---------------------------------------------------------------------------
# portable archive
# ---------------------------------------------------------------------------
def export_archive(session_payload: dict[str, Any], workspace: Workspace, path: str | Path,
                   app_version: str = "") -> tuple[Path, list[str]]:
    """Write session + attachments to a zip. Returns (path, problems).

    Attachments whose file is missing or changed since attaching are reported and left out
    rather than archived under a hash that no longer matches.
    """
    p = Path(path)
    if p.suffix.lower() != ARCHIVE_SUFFIX:
        p = p.with_suffix(ARCHIVE_SUFFIX)
    p.parent.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    manifest = {"format": "aerolab-archive", "schema_version": SCHEMA_VERSION, "app_version": app_version,
                "created": _now(), "files": []}
    tmp = p.with_suffix(p.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for att in workspace.attachments.values():
            src = Path(att.path)
            if not src.is_file():
                problems.append(f"{att.name}: file not found at {att.path}; not archived")
                continue
            if sha256_file(src) != att.sha256:
                problems.append(f"{att.name}: changed since it was attached (SHA-256 differs); not archived")
                continue
            z.write(src, att.archive_name)
            manifest["files"].append({"attachment_id": att.attachment_id, "name": att.archive_name,
                                      "sha256": att.sha256, "size": att.size})
        z.writestr("session.json", json.dumps(session_payload, indent=1))
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    os.replace(tmp, p)                 # never leave a half-written archive under the real name
    return p, problems


def _safe_member(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return False
    parts = PurePosixPath(name).parts
    return ".." not in parts and all(parts)


def _place_attachment(dest_root: Path, name: str, data: bytes, digest: str, attempts: int = 100) -> Path:
    """Write `data` under `dest_root`, or reuse an identical file already there.

    Every candidate name goes through the same checks (Codex review, finding 1):
    * it must be a plain name directly inside `dest_root` (no separators, no '..');
    * a path that is a link (even a dangling one) or anything but a regular file is skipped;
    * an existing regular file is reused only if its SHA-256 equals the archive's;
    * a new file is created exclusively (O_EXCL, and O_NOFOLLOW where the OS has it), so
      it can neither overwrite nor follow a link planted between the check and the write.
    """
    if not name or name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise WorkspaceError(f"unsafe attachment name {name!r}")
    stem, suffix = os.path.splitext(name)
    candidates = [name, f"{stem}_{digest[:8]}{suffix}"] + [f"{stem}_{digest[:8]}_{i}{suffix}"
                                                           for i in range(1, attempts)]
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for cand in candidates:
        target = dest_root / cand
        if target.parent != dest_root:
            continue
        if os.path.islink(target):
            continue
        if os.path.lexists(target):
            if target.is_file() and not os.path.islink(target) and sha256_file(target) == digest:
                return target
            continue
        try:
            fd = os.open(target, flags, 0o644)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except BaseException:
            try:
                os.unlink(target)
            finally:
                raise
        if sha256_file(target) != digest:           # paranoia: what landed is what was verified
            os.unlink(target)
            raise WorkspaceError(f"{name}: written file does not match its SHA-256")
        return target
    raise WorkspaceError(f"{name}: no free file name in {dest_root} after {attempts} attempts")


def import_archive(path: str | Path, extract_to: str | Path) -> tuple[dict[str, Any], list[str]]:
    """Read an archive: verify every member, extract attachments, re-point their paths.

    Refuses absolute paths, '..' components, drive letters, oversized members and
    suspicious compression ratios before writing anything. Returns (session payload, notes).
    """
    p = Path(path)
    dest = Path(extract_to)
    notes: list[str] = []
    try:
        z = zipfile.ZipFile(p)
    except (zipfile.BadZipFile, OSError) as exc:
        raise WorkspaceError(f"{p.name} is not a readable AeroLab archive ({exc})") from exc
    with z:
        infos = z.infolist()
        total = 0
        for info in infos:
            if not _safe_member(info.filename):
                raise WorkspaceError(f"unsafe path inside the archive: {info.filename!r}")
            if info.file_size > MAX_ARCHIVE_MEMBER:
                raise WorkspaceError(f"{info.filename} is too large ({info.file_size} bytes)")
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise WorkspaceError(f"{info.filename} has a suspicious compression ratio; refusing")
            total += info.file_size
        if total > MAX_ARCHIVE_TOTAL:
            raise WorkspaceError("the archive unpacks to more than 2 GB; refusing")
        names = {i.filename for i in infos}
        if "manifest.json" not in names or "session.json" not in names:
            raise WorkspaceError("the archive has no manifest.json/session.json")
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != "aerolab-archive":
            raise WorkspaceError("not an AeroLab archive")
        payload = json.loads(z.read("session.json").decode("utf-8"))
        payload, mig = migrate(payload)
        notes += mig
        ws = Workspace.from_dict(payload.get("workspace"))
        expected = {f["attachment_id"]: f for f in manifest.get("files", [])}
        dest.mkdir(parents=True, exist_ok=True)
        dest_root = dest.resolve()
        for aid, att in ws.attachments.items():
            entry = expected.get(aid)
            if entry is None or entry["name"] not in names:
                notes.append(f"{att.name}: not in the archive; the path still points at {att.path}")
                continue
            data = z.read(entry["name"])
            digest = hashlib.sha256(data).hexdigest()
            if digest != att.sha256 or digest != entry["sha256"]:
                raise WorkspaceError(f"{att.name}: SHA-256 mismatch inside the archive — it was altered")
            att.path = str(_place_attachment(dest_root, PurePosixPath(entry["name"]).name, data, digest))
        ws.log("archive imported", "session", f"{p.name}: {len(expected)} attachment(s) verified")
        payload["workspace"] = ws.to_dict()
    return payload, notes
