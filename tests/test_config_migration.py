from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import rdclient.config as config
import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Legacy plaintext migration is Linux-only")


class FakeKeyring:
    values: dict[str, str] = {}

    def __init__(self) -> None:
        pass

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _plain(value: str) -> str:
    return "plain:" + base64.b64encode(value.encode()).decode()


def test_legacy_linux_plaintext_secrets_move_to_keyring(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg" / "rd-desktop"
    old = tmp_path / ".rd-desktop"
    old.mkdir()
    legacy_file = old / "config.json"
    legacy_file.write_text(json.dumps({
        "public": {"auth_mode": "oauth", "language": "fr"},
        "secrets": {
            "client_id": _plain("cid"),
            "client_secret": _plain("secret"),
            "access_token": _plain("access"),
            "refresh_token": _plain("refresh"),
        },
    }))

    FakeKeyring.values = {}
    monkeypatch.setattr(config, "CONFIG_DIR", xdg)
    monkeypatch.setattr(config, "CONFIG_FILE", xdg / "config.json")
    monkeypatch.setattr(config, "LEGACY_LINUX_CONFIG_DIR", old)
    monkeypatch.setattr(config, "LEGACY_LINUX_CONFIG_FILE", legacy_file)
    monkeypatch.setattr(config, "_LinuxKeyringBackend", FakeKeyring)

    store = config.SecretStore()
    saved = json.loads((xdg / "config.json").read_text())
    assert store.public.language == "fr"
    assert FakeKeyring.values["refresh_token"] == "refresh"
    assert saved["secrets"] == {}
    assert not legacy_file.exists()


def test_legacy_linux_plaintext_is_discarded_when_no_secure_backend(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg" / "rd-desktop"
    old = tmp_path / ".rd-desktop"
    old.mkdir()
    legacy_file = old / "config.json"
    legacy_file.write_text(json.dumps({
        "public": {"auth_mode": "oauth", "language": "de", "access_expires_at": 9999999999},
        "secrets": {"refresh_token": _plain("insecure")},
    }))

    class MissingKeyring:
        def __init__(self):
            raise config.SecretStorageError("no keyring")

    monkeypatch.setattr(config, "CONFIG_DIR", xdg)
    monkeypatch.setattr(config, "CONFIG_FILE", xdg / "config.json")
    monkeypatch.setattr(config, "LEGACY_LINUX_CONFIG_DIR", old)
    monkeypatch.setattr(config, "LEGACY_LINUX_CONFIG_FILE", legacy_file)
    monkeypatch.setattr(config, "_LinuxKeyringBackend", MissingKeyring)

    store = config.SecretStore()
    saved = json.loads((xdg / "config.json").read_text())
    assert store.public.language == "de"
    assert store.public.auth_mode == ""
    assert store.public.access_expires_at == 0
    assert saved["secrets"] == {}
    assert not legacy_file.exists()
