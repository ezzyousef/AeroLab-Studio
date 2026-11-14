"""Licensing: enforcement is off, so nothing may be restricted, and licence files still verify.

Licences here are signed with a throwaway key generated in the test. The real private key is
never used or looked for.
"""
from __future__ import annotations

import base64
import secrets
import sys
from datetime import date
from pathlib import Path

import pytest

LABKIT = Path(r"E:\Lab Apps\labkit")


@pytest.fixture
def tmp_store(tmp_path):
    from aerolab import licensing as L
    return L.LicenceStore(L.PRODUCT, folder=tmp_path / "licence")


@pytest.fixture
def test_key(monkeypatch):
    """An Ed25519 key made for this test; the module trusts only its public half."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from aerolab import licensing as L

    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw,
                                        serialization.PublicFormat.Raw)
    monkeypatch.setattr(L, "PUBLIC_KEYS", {"test-key": base64.b64encode(raw).decode()})
    return key


def _make(key, product: str, **extra) -> str:
    if not (LABKIT / "labkit_issuer" / "issuer.py").exists():
        pytest.skip("labkit issuer is not available on this computer")
    if str(LABKIT) not in sys.path:
        sys.path.insert(0, str(LABKIT))
    from labkit_issuer.issuer import make_licence
    claims = {"product": product, "edition": "pro", "kind": "commercial",
              "serial": "AS-00001", "lid": secrets.token_hex(16),
              "issued": date.today().isoformat(), "name": "Test User"} | extra
    return make_licence(key, "test-key", claims)


def test_constants_keep_everything_free():
    from aerolab import licensing as L
    assert L.PRODUCT == "aerolab-studio"
    assert L.ENFORCE is False
    assert "*" in L.FREE_FEATURES
    assert L.RELEASE_DATE == date(2026, 11, 14)


def test_no_licence_reports_not_ok_but_allows_everything(tmp_store, monkeypatch):
    from aerolab import licensing as L
    monkeypatch.setattr(L, "store", lambda: tmp_store)
    st = L.status()
    assert not st.ok
    assert st.reason
    assert st.can_save
    for feature in ("origin-export", "excel-export", "anything-at-all", ""):
        assert L.allowed(feature)


def test_licence_signed_by_trusted_key_installs_and_verifies(tmp_store, test_key):
    from aerolab import licensing as L
    text = _make(test_key, L.PRODUCT, device=L.device_id())
    claims = L.install(text, tmp_store)
    assert claims["product"] == L.PRODUCT
    assert tmp_store.read() == text
    st = L.status(tmp_store)
    assert st.ok, st.reason
    assert st.edition == "pro"
    assert st.entitled("anything")          # FREE_FEATURES contains "*"


def test_licence_for_another_product_is_refused(tmp_store, test_key):
    from aerolab import licensing as L
    text = _make(test_key, "some-other-product")
    with pytest.raises(L.LicenceError, match="some-other-product"):
        L.install(text, tmp_store)
    assert tmp_store.read() is None
    assert L.allowed("anything")


def test_dialog_shows_device_id_and_installs(qapp, tmp_path, tmp_store, test_key, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog
    from aerolab import licensing as L
    from aerolab.ui.licence_dialog import LicenceDialog

    dialog = LicenceDialog(store=tmp_store)
    dialog.show()
    qapp.processEvents()
    assert dialog.device_field.text() == L.device_id()
    assert dialog.device_field.isReadOnly()
    assert "available" in dialog.status_label.text()

    dialog.copy_request()
    assert QApplication.clipboard().text() == L.activation_request()

    bad = tmp_path / "other.json"
    bad.write_text(_make(test_key, "some-other-product"), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    dialog.choose_file()
    assert "some-other-product" in dialog.message_label.text()

    good = tmp_path / "good.json"
    good.write_text(_make(test_key, L.PRODUCT, device=L.device_id()), encoding="utf-8")
    assert dialog.install_file(str(good))
    assert dialog.edition_label.text().startswith("Pro")
    dialog.close()


def test_help_menu_opens_the_licence_dialog(qapp, monkeypatch, tmp_store):
    from PySide6.QtWidgets import QMenu
    from aerolab import licensing as L
    from aerolab.ui.app import MainWindow
    from aerolab.ui.state import Session

    monkeypatch.setattr(L, "store", lambda: tmp_store)
    window = MainWindow(Session())
    help_menu = [m for m in window.menuBar().findChildren(QMenu) if m.title() == "&Help"][0]
    assert any(a.text().startswith("&Licence") for a in help_menu.actions())
    dialog = window.show_licence()
    qapp.processEvents()
    assert dialog.device_field.text() == L.device_id()
    dialog.close()
    window.close()
