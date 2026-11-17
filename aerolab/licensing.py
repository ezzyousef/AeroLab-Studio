"""AeroLab Studio's licence settings, on top of the shared ``labkit.licence`` module.

Enforcement is OFF. Prices and editions have not been decided, so every feature stays free
(``FREE_FEATURES = {"*"}``) and ``allowed()`` always answers True while ``ENFORCE`` is False.
A missing or invalid licence never blocks anything; it is only reported in the Licence dialog.
Nothing here touches the network.
"""
from __future__ import annotations

from datetime import date

from .vendor import licence
from .vendor.licence import LicenceError, LicenceStore, Status

__all__ = ["PRODUCT", "PUBLIC_KEYS", "RELEASE_DATE", "ENFORCE", "FREE_FEATURES", "status",
           "allowed", "store", "device_id", "activation_request", "install", "LicenceError",
           "Status"]

PRODUCT = "aerolab-studio"
PUBLIC_KEYS = {"labapps-2026": "g93gW00t+FyNNul4QhlGPReeosESePiX9vmr0UEL6hs="}
RELEASE_DATE = date(2026, 11, 14)
ENFORCE = False
FREE_FEATURES = frozenset({"*"})        # everything is free while ENFORCE is False


def store() -> LicenceStore:
    return LicenceStore(PRODUCT)


def status(licence_store: LicenceStore | None = None) -> Status:
    """The installed licence's status for this computer. Never raises."""
    try:
        return licence.check(PRODUCT, PUBLIC_KEYS, store=licence_store or store(),
                             release_date=RELEASE_DATE, free_features=FREE_FEATURES)
    except Exception as exc:                                    # noqa: BLE001 - report, never crash
        return Status(ok=False, reason=f"The licence could not be checked: {exc}",
                      features=FREE_FEATURES)


def allowed(feature: str) -> bool:
    """May the user use ``feature``? Always True while enforcement is off."""
    if not ENFORCE:
        return True
    return status().entitled(feature)


def device_id() -> str:
    return licence.device_id(PRODUCT)


def activation_request() -> str:
    return licence.activation_request(PRODUCT)


def install(text: str, licence_store: LicenceStore | None = None) -> dict:
    """Verify and save a licence file's text. Raises LicenceError with a user-facing sentence."""
    return (licence_store or store()).install(text, PRODUCT, PUBLIC_KEYS)
