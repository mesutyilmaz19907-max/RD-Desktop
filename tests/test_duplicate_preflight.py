from __future__ import annotations

import hashlib

from rdclient.app import AppController


class FakeAPI:
    def __init__(self, existing):
        self.existing = existing
        self.add_torrent_calls = 0
        self.add_magnet_calls = 0

    def torrents(self):
        return list(self.existing)

    def add_torrent(self, _path):
        self.add_torrent_calls += 1
        return {"id": "new-torrent"}

    def add_magnet(self, _magnet):
        self.add_magnet_calls += 1
        return {"id": "new-magnet"}


def controller(api):
    app = object.__new__(AppController)
    app.api = api
    app.language = "en"
    app._wait_for_files = lambda tid: {"id": tid, "files": [{"id": 1}]}
    return app


def test_existing_magnet_is_skipped_before_add():
    info_hash = "0123456789abcdef0123456789abcdef01234567"
    api = FakeAPI([{"id": "existing", "hash": info_hash.upper(), "filename": "same.mkv"}])
    app = controller(api)

    result = app._add_single_item_checked("magnet", f"magnet:?xt=urn:btih:{info_hash}&dn=same")

    assert result["skipped"] is True
    assert result["existing"]["id"] == "existing"
    assert api.add_magnet_calls == 0


def test_existing_torrent_file_is_skipped_before_upload(tmp_path):
    info = b"d4:name8:same.mkv6:lengthi100ee"
    expected = hashlib.sha1(info).hexdigest()
    path = tmp_path / "same.torrent"
    path.write_bytes(b"d4:info" + info + b"e")
    api = FakeAPI([{"id": "existing", "hash": expected, "filename": "same.mkv"}])
    app = controller(api)

    result = app._add_single_item_checked("torrent", str(path))

    assert result["skipped"] is True
    assert api.add_torrent_calls == 0


def test_new_magnet_is_added_normally():
    info_hash = "0123456789abcdef0123456789abcdef01234567"
    api = FakeAPI([])
    app = controller(api)

    result = app._add_single_item_checked("magnet", f"magnet:?xt=urn:btih:{info_hash}")

    assert result["skipped"] is False
    assert result["tid"] == "new-magnet"
    assert api.add_magnet_calls == 1
