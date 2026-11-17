# Vendored from labkit (feature/licence-sdk) labkit/licence.py — edit there, not here.
"""labkit.licence: offline-verifiable, device-bound licences shared by the lab applications.

Built from Figure Studio's proven design (Ed25519 signatures, a hashed device identifier,
"one licence, one computer"), generalised so one implementation serves every product.

What it is
- **Verification only.** The application holds public keys. The private key lives with the
  author's issuer tool (``labkit_issuer``, never vendored) or a licence service. Nothing in a
  distributed build can mint a licence.
- **Every claim is signed**, including ``product``, ``edition``, ``features`` and ``device``, so a
  licence for one product, edition or computer cannot be edited into another.
- **Keys are named** (``kid``). A product can trust several keys (author key, online-service
  key, a rotated key), and a revoked key can be dropped from the next release.
- **Privacy:** the device identifier is a one-way hash of Windows' installation GUID and the
  system drive serial, *salted with the product name*, so two products cannot correlate a
  computer. No network access happens here, ever.
- **Never punitive:** this module only reports status. Applications must keep opening, saving
  and exporting the user's own work when a licence is missing or expired (see ``Status.can_save``).

What it is not
- Not tamper-proof. Client-side checks can be patched out of any offline application
  (CWE-602). This raises the cost of casual sharing; server-side entitlements are the only
  real boundary for high-value features.
- The local clock can be set back. ``check()`` notices a clock that moved back relative to the
  last run and reports it, but a determined user with a VM can defeat any offline expiry.

Licence file (JSON)::

    {"format": "labkit-licence/1", "kid": "author-2026",
     "licence": {"product": "supercap-suite", "edition": "pro", "kind": "commercial",
                 "features": ["origin-export"], "serial": "SC-0001", "lid": "<32 hex>",
                 "name": "...", "organisation": "...", "issued": "2026-11-14",
                 "expires": "", "maintenance_until": "2027-11-14", "device": "ABCD-..."},
     "signature": "<base64 Ed25519 over canonical(licence)>"}
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import socket
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

FORMAT = "labkit-licence/1"
MAX_BYTES = 64 * 1024
KINDS = ("free", "trial", "student", "academic", "commercial", "team", "enterprise")
REQUIRED = ("product", "edition", "kind", "serial", "lid", "issued")
OPTIONAL_STR = ("name", "organisation", "expires", "maintenance_until", "device", "binding")
DATE_FIELDS = ("issued", "expires", "maintenance_until")
CLOCK_TOLERANCE = timedelta(days=2)   # time-zone changes and small corrections are normal


class LicenceError(ValueError):
    """The text is not a trustworthy licence for this product."""


# ------------------------------------------------------------------------------- canonical
def canonical(claims: dict) -> bytes:
    """The exact bytes that are signed: sorted keys, no whitespace, ASCII only.

    Only strings, booleans, integers and lists of strings are allowed, so the encoding is
    unambiguous across Python and JavaScript implementations.
    """
    for k, v in claims.items():
        if not isinstance(k, str):
            raise LicenceError("claim names must be text")
        ok = isinstance(v, (str, bool, int)) or (isinstance(v, list) and all(isinstance(x, str) for x in v))
        if not ok or isinstance(v, float):
            raise LicenceError(f"claim {k!r} has an unsupported type")
    return json.dumps(claims, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


# ------------------------------------------------------------------------------- device id
def _machine_guid() -> str:
    if os.name != "nt":
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                return Path(p).read_text().strip()
            except OSError:
                continue
        return ""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        try:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
        finally:
            winreg.CloseKey(key)
    except OSError:
        return ""


def _volume_serial() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        serial = ctypes.c_ulong(0)
        root = os.environ.get("SystemDrive", "C:") + "\\"
        ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), None, 0,
                                                          ctypes.byref(serial), None, None, None, 0)
        return "%08X" % serial.value if ok else ""
    except (OSError, AttributeError):
        return ""


def device_id(product: str, _parts: list[str] | None = None) -> str:
    """Stable per-computer, per-product identifier, e.g. ``7F3A-91C2-04BD-E816``.

    Survives reinstalling the application and renaming the computer; changes when Windows is
    reinstalled or the system drive is reformatted (the licence holder then asks for a move).
    Falls back to the network card address and host name only when neither Windows value is
    readable. ``_parts`` exists for tests.
    """
    parts = _parts if _parts is not None else [_machine_guid(), _volume_serial()]
    if not any(parts):
        parts = ["%012X" % uuid.getnode(), socket.gethostname()]
    digest = hashlib.sha256(("labkit-device|" + product + "|" + "|".join(parts)).encode("utf-8", "replace"))
    h = digest.hexdigest().upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


DEVICE_RE = re.compile(r"^[0-9A-F]{4}(-[0-9A-F]{4}){3}$")


def activation_request(product: str, device: str | None = None) -> str:
    """Text a user sends (by e-mail, form, USB...) to obtain a licence for an offline computer.

    It carries only the product name and the hashed device id, plus a checksum so typing
    mistakes are caught. No personal data.
    """
    device = device or device_id(product)
    body = f"{product}:{device}"
    check = hashlib.sha256(body.encode()).hexdigest()[:6].upper()
    return f"REQ-{base64.b32encode(body.encode()).decode().rstrip('=')}-{check}"


def parse_activation_request(text: str) -> tuple[str, str]:
    """Inverse of activation_request (used by the issuer). Raises LicenceError if damaged."""
    m = re.fullmatch(r"REQ-([A-Z2-7]+)-([0-9A-F]{6})", (text or "").strip().upper())
    if not m:
        raise LicenceError("That is not an activation request.")
    raw = m.group(1) + "=" * (-len(m.group(1)) % 8)
    try:
        body = base64.b32decode(raw).decode()
    except (ValueError, UnicodeDecodeError) as e:
        raise LicenceError("The activation request is damaged.") from e
    if hashlib.sha256(body.encode()).hexdigest()[:6].upper() != m.group(2):
        raise LicenceError("The activation request was mistyped (checksum mismatch).")
    product, _, device = body.partition(":")
    if not product or not DEVICE_RE.match(device):
        raise LicenceError("The activation request is damaged.")
    return product, device


# ------------------------------------------------------------------------------- verify
def _parse_date(text: str, name: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise LicenceError(f"The licence has an unreadable {name} date.") from e


def verify(text: str, product: str, public_keys: dict[str, str]) -> dict:
    """Return the signed claims if ``text`` is a genuine licence for ``product``.

    Checks structure, signature (against the key named by ``kid``), product and field types.
    Does **not** check dates or the computer; ``check()`` does that. Raises LicenceError with a
    sentence suitable for the user.
    """
    not_licence = LicenceError("That file is not a licence for this application.")
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise not_licence
    try:
        doc = json.loads(text)
    except ValueError:
        raise not_licence from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise not_licence
    claims, kid, sig_text = doc.get("licence"), doc.get("kid"), doc.get("signature")
    if not isinstance(claims, dict) or not isinstance(kid, str) or not isinstance(sig_text, str):
        raise not_licence
    key_b64 = public_keys.get(kid)
    if not key_b64:
        raise LicenceError("This licence was signed with a key this version does not trust. "
                           "Ask for a reissued licence.")
    try:
        signature = base64.b64decode(sig_text, validate=True)
        raw_key = base64.b64decode(key_b64, validate=True)
    except ValueError:
        raise not_licence from None
    if len(signature) != 64 or len(raw_key) != 32:
        raise not_licence
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:  # pragma: no cover - packaging error
        raise LicenceError("This build cannot check licences: the 'cryptography' package is missing.") from e
    try:
        Ed25519PublicKey.from_public_bytes(raw_key).verify(signature, canonical(claims))
    except InvalidSignature:
        raise LicenceError("That licence has been altered, or it was not issued for this application.") from None
    # signed, so the issuer wrote these; still validate shape so a buggy issuer fails loudly
    for k in REQUIRED:
        if not isinstance(claims.get(k), str) or not claims[k]:
            raise LicenceError(f"The licence is missing '{k}'.")
    for k in OPTIONAL_STR:
        if k in claims and not isinstance(claims[k], str):
            raise not_licence
    if not isinstance(claims.get("features", []), list):
        raise not_licence
    if claims["product"] != product:
        raise LicenceError(f"That licence is for '{claims['product']}', not this application.")
    if claims["kind"] not in KINDS:
        raise not_licence
    for k in DATE_FIELDS:
        _parse_date(claims.get(k, ""), k)
    if claims.get("binding") == "device" and not DEVICE_RE.match(claims.get("device", "")):
        raise not_licence
    return claims


# ------------------------------------------------------------------------------- status
@dataclass
class Status:
    """What the application may do. ``ok`` false never means "lock the user's files"."""
    ok: bool
    reason: str = ""                       # one sentence for the user when not ok / warnings
    claims: dict = field(default_factory=dict)
    edition: str = "free"
    features: frozenset = frozenset()
    expires: date | None = None
    days_left: int | None = None
    warnings: list[str] = field(default_factory=list)
    can_save: bool = True                  # always True: user data is never held hostage

    def entitled(self, feature: str) -> bool:
        return self.ok and (feature in self.features or "*" in self.features)


def eligible_for(claims: dict, release_date: date) -> bool:
    """Perpetual licences with maintenance: versions released on or before
    ``maintenance_until`` keep working forever; later versions need a renewal."""
    until = _parse_date(claims.get("maintenance_until", ""), "maintenance")
    return until is None or release_date <= until


class LicenceStore:
    """Where a product keeps its licence and its small tamper-evident state file."""

    def __init__(self, product: str, folder: Path | None = None):
        self.product = product
        base = folder or Path(os.environ.get("APPDATA") or Path.home() / ".config") / "LabApps" / product
        self.folder = Path(base)
        self.licence_path = self.folder / "licence.json"
        self.state_path = self.folder / "licence-state.json"

    def read(self) -> str | None:
        try:
            return self.licence_path.read_text(encoding="utf-8")
        except OSError:
            return None

    def install(self, text: str, product: str, public_keys: dict[str, str]) -> dict:
        """Verify first, then save atomically. A bad file never replaces a good one."""
        claims = verify(text, product, public_keys)
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.licence_path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.licence_path)
        return claims

    def _state_mac(self, data: dict, device: str) -> str:
        msg = json.dumps({k: data[k] for k in sorted(data) if k != "mac"}, sort_keys=True).encode()
        return hmac.new(("labkit-state|" + self.product + "|" + device).encode(), msg, hashlib.sha256).hexdigest()[:32]

    def last_seen(self, device: str) -> date | None:
        """Latest date the app ran on this device; None if the state file is absent or edited."""
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("mac") != self._state_mac(data, device):
                return None
            return date.fromisoformat(data["last_seen"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def record_seen(self, device: str, today: date) -> None:
        prev = self.last_seen(device)
        data = {"last_seen": max(today, prev).isoformat() if prev else today.isoformat()}
        data["mac"] = self._state_mac(data, device)
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            pass  # state is a hint, never a reason to fail


def check(product: str, public_keys: dict[str, str], *, store: LicenceStore | None = None,
          release_date: date | None = None, grace_days: int = 0, today: date | None = None,
          device: str | None = None, free_features: frozenset = frozenset()) -> Status:
    """Full check of the installed licence for this computer, today.

    ``free_features`` are what the application offers without a licence. ``grace_days`` lets a
    subscription keep working a little after ``expires`` (with a warning) so a late renewal
    never interrupts work.
    """
    store = store or LicenceStore(product)
    today = today or date.today()
    device = device or device_id(product)
    free = Status(ok=False, edition="free", features=frozenset(free_features))
    text = store.read()
    if text is None:
        free.reason = "No licence installed."
        return free
    try:
        claims = verify(text, product, public_keys)
    except LicenceError as e:
        free.reason = str(e)
        return free

    warnings = []
    seen = store.last_seen(device)
    effective_today = today
    if seen and today + CLOCK_TOLERANCE < seen:
        warnings.append("This computer's clock appears to have been set back; dates are checked "
                        f"against {seen.isoformat()}.")
        effective_today = seen
    store.record_seen(device, today)

    bound = claims.get("device", "")
    if bound and bound != device:
        free.reason = (f"This licence belongs to another computer. This computer's id is {device}; "
                       "send it to the publisher to move the licence.")
        free.claims = claims
        return free
    if release_date and not eligible_for(claims, release_date):
        free.reason = (f"Your licence covers versions released up to {claims['maintenance_until']}. "
                       "Keep using that version, or renew to use this one.")
        free.claims = claims
        return free
    expires = _parse_date(claims.get("expires", ""), "expiry")
    days_left = None
    if expires:
        days_left = (expires - effective_today).days
        if days_left < -grace_days:
            free.reason = f"The licence expired on {expires.isoformat()}. Your files remain fully available."
            free.claims, free.expires, free.days_left = claims, expires, days_left
            return free
        if days_left < 0:
            warnings.append(f"The licence expired on {expires.isoformat()}; it keeps working for "
                            f"{grace_days + days_left} more day(s) while you renew.")
        elif days_left <= 14:
            warnings.append(f"The licence expires in {days_left} day(s).")
    feats = frozenset(claims.get("features", [])) | frozenset(free_features)
    return Status(ok=True, claims=claims, edition=claims["edition"], features=feats, expires=expires,
                  days_left=days_left, warnings=warnings, reason="; ".join(warnings))
