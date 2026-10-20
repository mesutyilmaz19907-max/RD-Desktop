from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from rdclient.downloads import IncompleteDownloadError, download_file, reconcile_job


class Response:
    def __init__(self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}
    def read(self, size=-1):
        return self._body.read(size)
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False


def test_truncated_response_never_becomes_completed(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Response(b"12345", headers={"Content-Length": "10"}))
    dest = tmp_path / "file.bin"
    with pytest.raises(IncompleteDownloadError):
        download_file(url="https://example.test/file", destination=str(dest), stop_action=lambda: None, progress=lambda *_a: None)
    assert not dest.exists()
    assert (tmp_path / "file.bin.part").read_bytes() == b"12345"


def test_complete_response_is_atomically_promoted(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Response(b"12345", headers={"Content-Length": "5"}))
    dest = tmp_path / "file.bin"
    result = download_file(url="https://example.test/file", destination=str(dest), stop_action=lambda: None, progress=lambda *_a: None)
    assert result.status == "Completed"
    assert dest.read_bytes() == b"12345"
    assert not (tmp_path / "file.bin.part").exists()


def test_restart_reconciliation_uses_partial_file_size(tmp_path):
    dest = tmp_path / "file.bin"
    Path(str(dest) + ".part").write_bytes(b"abc")
    job = reconcile_job({"id": 1, "dest": str(dest), "status": "Downloading", "downloaded": 0, "total": 10})
    assert job["status"] == "Paused"
    assert job["downloaded"] == 3


def test_download_does_not_change_destination_directory_permissions(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX permission regression")
    destination_dir = tmp_path / "shared-downloads"
    destination_dir.mkdir(mode=0o755)
    destination_dir.chmod(0o755)
    destination = destination_dir / "payload.bin"

    class Response:
        status = 200
        headers = {"Content-Length": "3"}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _size):
            if getattr(self, "sent", False):
                return b""
            self.sent = True
            return b"abc"

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    result = download_file(
        url="https://example.invalid/file",
        destination=str(destination),
        expected_total=3,
        stop_action=lambda: None,
        progress=lambda *args: None,
    )
    assert result.status == "Completed"
    assert (destination_dir.stat().st_mode & 0o777) == 0o755
