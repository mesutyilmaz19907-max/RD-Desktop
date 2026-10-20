from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from rdclient.api import HTTPResult, RealDebridAPI


class DummyStore:
    public = SimpleNamespace(auth_mode="oauth", access_expires_at=10**20)
    def get(self, key):
        return "TOKEN" if key == "access_token" else None


class CaptureAPI(RealDebridAPI):
    def __init__(self):
        super().__init__(DummyStore())
        self.calls = []
    def _send(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return HTTPResult(200, {"Content-Type": "application/json"}, b"{}")


def test_add_torrent_is_raw_put():
    api = CaptureAPI()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.torrent"
        p.write_bytes(b"abc123")
        api.add_torrent(str(p))
    method, url, kwargs = api.calls[-1]
    assert method == "PUT"
    assert url.endswith("/torrents/addTorrent")
    assert kwargs["content"] == b"abc123"
    assert kwargs["headers"]["Content-Type"] == "application/x-bittorrent"


def test_select_files_comma_separated():
    api = CaptureAPI()
    api.select_files("abc", [1, 4, 9])
    method, url, kwargs = api.calls[-1]
    assert method == "POST"
    assert url.endswith("/torrents/selectFiles/abc")
    assert kwargs["data"]["files"] == "1,4,9"


def test_delete_uses_delete_verb():
    api = CaptureAPI()
    api.delete_torrent("xyz")
    method, url, kwargs = api.calls[-1]
    assert method == "DELETE"
    assert url.endswith("/torrents/delete/xyz")


def test_unrestrict_is_post():
    api = CaptureAPI()
    api.unrestrict_link("https://example.invalid/file")
    method, url, kwargs = api.calls[-1]
    assert method == "POST"
    assert url.endswith("/unrestrict/link")
    assert kwargs["data"]["link"] == "https://example.invalid/file"
