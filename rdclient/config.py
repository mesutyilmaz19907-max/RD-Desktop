from __future__ import annotations

import base64
import ctypes
import json
import os
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Protocol

from .constants import APP_NAME
from .platform_support import atomic_write_text, config_dir, ensure_private_dir, ensure_private_file

CONFIG_DIR = config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
LEGACY_LINUX_CONFIG_DIR = Path.home() / ".rd-desktop"
LEGACY_LINUX_CONFIG_FILE = LEGACY_LINUX_CONFIG_DIR / "config.json"
_SECRET_KEYS = ("client_id", "client_secret", "access_token", "refresh_token")


class SecretStorageError(RuntimeError):
    pass


@dataclass
class PublicConfig:
    auth_mode: str = ""
    access_expires_at: float = 0.0
    download_dir: str = str(Path.home() / "Downloads")
    auto_select_all: bool = False
    max_simultaneous_downloads: int = 3
    language: str = "en"


class SecretBackend(Protocol):
    def get(self, key: str) -> Optional[str]: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class _WindowsDPAPIBackend:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def __init__(self, encrypted: dict[str, str]) -> None:
        self.encrypted = encrypted
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def _protect(self, raw: bytes) -> str:
        buf = ctypes.create_string_buffer(raw)
        in_blob = self.DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        out_blob = self.DATA_BLOB()
        if not self._crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            raise ctypes.WinError()
        try:
            protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return base64.b64encode(protected).decode("ascii")
        finally:
            self._kernel32.LocalFree(out_blob.pbData)

    def _unprotect(self, value: str) -> bytes:
        protected = base64.b64decode(value.encode("ascii"))
        buf = ctypes.create_string_buffer(protected)
        in_blob = self.DATA_BLOB(len(protected), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        out_blob = self.DATA_BLOB()
        if not self._crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            self._kernel32.LocalFree(out_blob.pbData)

    def get(self, key: str) -> Optional[str]:
        value = self.encrypted.get(key)
        if not value:
            return None
        try:
            return self._unprotect(value).decode("utf-8")
        except Exception:
            return None

    def set(self, key: str, value: str) -> None:
        self.encrypted[key] = self._protect(value.encode("utf-8"))

    def delete(self, key: str) -> None:
        self.encrypted.pop(key, None)


class _LinuxKeyringBackend:
    def __init__(self) -> None:
        try:
            import keyring
            from keyring.errors import KeyringError
        except ImportError as exc:
            raise SecretStorageError(
                "Linux credential storage requires the 'keyring' package. Install project dependencies and sign in again."
            ) from exc
        self._keyring = keyring
        self._error_type = KeyringError
        try:
            backend = keyring.get_keyring()
            priority = float(getattr(backend, "priority", 0) or 0)
        except Exception as exc:
            raise SecretStorageError("No usable Linux system keyring is available.") from exc
        if priority <= 0:
            raise SecretStorageError(
                "No usable Linux Secret Service/keyring backend is available. Start a desktop keyring service and try again."
            )

    @staticmethod
    def _username(key: str) -> str:
        return f"rd-desktop:{key}"

    def get(self, key: str) -> Optional[str]:
        try:
            return self._keyring.get_password(APP_NAME, self._username(key))
        except self._error_type as exc:
            raise SecretStorageError(f"Could not read '{key}' from the system keyring: {exc}") from exc

    def set(self, key: str, value: str) -> None:
        try:
            self._keyring.set_password(APP_NAME, self._username(key), value)
        except self._error_type as exc:
            raise SecretStorageError(f"Could not store '{key}' in the system keyring: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(APP_NAME, self._username(key))
        except Exception:
            # Missing key and backend-specific deletion errors should not block logout.
            pass


class SecretStore:
    """Public settings + OS-native secret storage.

    Windows keeps OAuth secrets encrypted with DPAPI in config.json. Linux puts
    secrets in the desktop keyring and never writes token material to config.json.
    A legacy ~/.rd-desktop config is migrated on Linux when possible.
    """

    def __init__(self) -> None:
        ensure_private_dir(CONFIG_DIR)
        self.public = PublicConfig()
        self._memory: dict[str, str] = {}
        self._encrypted: dict[str, str] = {}
        self._backend: SecretBackend | None = None
        self._loaded_from_legacy = False
        self._load()
        self._configure_backend_and_migrate()

    def _source_config(self) -> Path:
        if CONFIG_FILE.exists():
            return CONFIG_FILE
        if os.name != "nt" and LEGACY_LINUX_CONFIG_FILE.exists():
            return LEGACY_LINUX_CONFIG_FILE
        return CONFIG_FILE

    def _load(self) -> None:
        source = self._source_config()
        if not source.exists():
            return
        self._loaded_from_legacy = source == LEGACY_LINUX_CONFIG_FILE
        if self._loaded_from_legacy:
            ensure_private_file(source)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            pub = data.get("public", data)
            allowed = set(asdict(PublicConfig()).keys())
            self.public = PublicConfig(**{k: pub[k] for k in allowed if k in pub})
            self._encrypted = dict(data.get("secrets", {}))
        except Exception:
            self.public = PublicConfig()
            self._encrypted = {}

    def _configure_backend_and_migrate(self) -> None:
        if os.name == "nt":
            self._backend = _WindowsDPAPIBackend(self._encrypted)
            return

        # Delay failure until a secret is actually needed so the UI can start
        # and display a useful sign-in error even on minimal Linux installs.
        try:
            self._backend = _LinuxKeyringBackend()
        except SecretStorageError:
            self._backend = None

        legacy_plain: dict[str, str] = {}
        for key, value in list(self._encrypted.items()):
            if isinstance(value, str) and value.startswith("plain:"):
                try:
                    legacy_plain[key] = base64.b64decode(value[6:].encode("ascii")).decode("utf-8")
                except Exception:
                    continue
        if legacy_plain and self._backend is not None:
            for key, value in legacy_plain.items():
                self._backend.set(key, value)
            self._encrypted.clear()

        if self._loaded_from_legacy:
            # Never leave the old reversible Linux secret file behind. If no
            # system keyring is available we deliberately discard those legacy
            # credentials and require a fresh sign-in instead of perpetuating
            # insecure storage. Public settings still migrate to XDG.
            if legacy_plain and self._backend is None:
                self._encrypted.clear()
                self.public.auth_mode = ""
                self.public.access_expires_at = 0.0
            self.save()
            try:
                LEGACY_LINUX_CONFIG_FILE.unlink(missing_ok=True)
            except OSError:
                pass

    def _require_backend(self) -> SecretBackend:
        if self._backend is not None:
            return self._backend
        if os.name != "nt":
            self._backend = _LinuxKeyringBackend()
            return self._backend
        raise SecretStorageError("Credential storage backend is unavailable.")

    def save(self) -> None:
        ensure_private_dir(CONFIG_DIR)
        secrets = self._encrypted if os.name == "nt" else {}
        payload = {"version": 2, "public": asdict(self.public), "secrets": secrets}
        atomic_write_text(CONFIG_FILE, json.dumps(payload, indent=2, ensure_ascii=False))

    def get(self, key: str) -> Optional[str]:
        if key in self._memory:
            return self._memory[key]
        if key not in _SECRET_KEYS:
            return None
        try:
            value = self._require_backend().get(key)
        except SecretStorageError:
            # Login UI can still open and report a clear storage error when save is attempted.
            return None
        if value is not None:
            self._memory[key] = value
        return value

    def set(self, key: str, value: str, persistent: bool = True) -> None:
        self._memory[key] = value
        if persistent:
            self._require_backend().set(key, value)
        else:
            try:
                self._require_backend().delete(key)
            except SecretStorageError:
                pass
        self.save()

    def delete(self, key: str) -> None:
        self._memory.pop(key, None)
        try:
            self._require_backend().delete(key)
        except SecretStorageError:
            pass
        self.save()

    def clear_auth(self) -> None:
        for key in _SECRET_KEYS:
            self._memory.pop(key, None)
            try:
                self._require_backend().delete(key)
            except SecretStorageError:
                pass
        self._encrypted.clear()
        self.public.auth_mode = ""
        self.public.access_expires_at = 0.0
        self.save()

    def save_oauth(
        self,
        *,
        client_id: str,
        client_secret: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        persistent: bool = True,
    ) -> None:
        # Validate storage before clearing a working session.
        backend = self._require_backend() if persistent else None
        values = {
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
        if persistent and backend is not None:
            for key, value in values.items():
                backend.set(key, value)
        for key, value in values.items():
            self._memory[key] = value
        self.public.auth_mode = "oauth"
        self.public.access_expires_at = time.time() + max(0, int(expires_in) - 60)
        self.save()

    def update_oauth_tokens(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        backend = self._require_backend()
        backend.set("access_token", access_token)
        backend.set("refresh_token", refresh_token)
        self._memory["access_token"] = access_token
        self._memory["refresh_token"] = refresh_token
        self.public.auth_mode = "oauth"
        self.public.access_expires_at = time.time() + max(0, int(expires_in) - 60)
        self.save()
