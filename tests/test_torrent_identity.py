from __future__ import annotations

import base64
import hashlib

import pytest

from rdclient.torrent_identity import (
    TorrentIdentityError,
    magnet_info_hash,
    normalize_info_hash,
    torrent_file_info_hash,
)


def test_normalize_hex_and_base32_hashes():
    raw = bytes(range(20))
    hex_hash = raw.hex()
    b32_hash = base64.b32encode(raw).decode("ascii")
    assert normalize_info_hash(hex_hash.upper()) == hex_hash
    assert normalize_info_hash(b32_hash.lower()) == hex_hash


def test_extracts_btih_from_magnet_case_insensitively():
    value = "0123456789ABCDEF0123456789ABCDEF01234567"
    magnet = f"magnet:?dn=Example&xt=URN:BTIH:{value}"
    assert magnet_info_hash(magnet) == value.lower()


def test_torrent_hashes_exact_raw_info_dictionary(tmp_path):
    # The info dictionary deliberately uses a particular byte ordering. The
    # expected identity is the SHA-1 of those exact bytes, not a re-encoding.
    info = b"d4:name4:test6:lengthi123ee"
    torrent = b"d8:announce15:https://tracker4:info" + info + b"e"
    path = tmp_path / "sample.torrent"
    path.write_bytes(torrent)
    assert torrent_file_info_hash(path) == hashlib.sha1(info).hexdigest()


def test_torrent_without_info_is_rejected(tmp_path):
    path = tmp_path / "bad.torrent"
    path.write_bytes(b"d4:name4:teste")
    with pytest.raises(TorrentIdentityError):
        torrent_file_info_hash(path)
