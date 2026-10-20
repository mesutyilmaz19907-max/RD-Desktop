from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


class TorrentIdentityError(ValueError):
    """Raised when a .torrent file cannot be inspected safely."""


def normalize_info_hash(value: object) -> str | None:
    """Return a canonical 40-character lowercase BTIH hash when possible."""
    text = str(value or "").strip()
    if len(text) == 40:
        try:
            int(text, 16)
        except ValueError:
            return None
        return text.lower()
    if len(text) == 32:
        try:
            raw = base64.b32decode(text.upper(), casefold=True)
        except (ValueError, base64.binascii.Error):
            return None
        if len(raw) == 20:
            return raw.hex()
    return None


def magnet_info_hash(magnet: str) -> str | None:
    """Extract and normalize the BitTorrent v1 info hash from a magnet URI."""
    try:
        parts = urlsplit(magnet.strip())
    except ValueError:
        return None
    if parts.scheme.lower() != "magnet":
        return None
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        if key.lower() != "xt":
            continue
        prefix = "urn:btih:"
        if value.lower().startswith(prefix):
            return normalize_info_hash(value[len(prefix) :])
    return None


def torrent_file_info_hash(path: str | Path) -> str:
    """Calculate a .torrent's v1 info hash from the exact bencoded info bytes.

    Re-encoding the dictionary can change byte ordering and therefore the hash,
    so the parser locates the original top-level ``info`` value and hashes its
    raw byte span exactly as stored in the file.
    """
    data = Path(path).read_bytes()
    start, end = _top_level_value_span(data, b"info")
    return hashlib.sha1(data[start:end]).hexdigest()


def item_info_hash(kind: str, value: str) -> str | None:
    """Best-effort identity for an upload-queue item."""
    if kind == "magnet":
        return magnet_info_hash(value)
    if kind == "torrent":
        try:
            return torrent_file_info_hash(value)
        except (OSError, TorrentIdentityError, ValueError):
            return None
    return None


def _read_bytes(data: bytes, pos: int) -> tuple[bytes, int]:
    if pos >= len(data) or not 48 <= data[pos] <= 57:
        raise TorrentIdentityError("Expected bencoded byte string")
    colon = data.find(b":", pos)
    if colon < 0:
        raise TorrentIdentityError("Invalid bencoded byte string")
    length_bytes = data[pos:colon]
    if not length_bytes or (len(length_bytes) > 1 and length_bytes.startswith(b"0")):
        raise TorrentIdentityError("Invalid bencoded byte-string length")
    try:
        length = int(length_bytes)
    except ValueError as exc:
        raise TorrentIdentityError("Invalid bencoded byte-string length") from exc
    start = colon + 1
    end = start + length
    if end > len(data):
        raise TorrentIdentityError("Truncated bencoded byte string")
    return data[start:end], end


def _skip_value(data: bytes, pos: int) -> int:
    if pos >= len(data):
        raise TorrentIdentityError("Unexpected end of bencoded data")
    token = data[pos]
    if 48 <= token <= 57:
        _, return_pos = _read_bytes(data, pos)
        return return_pos
    if token == ord("i"):
        end = data.find(b"e", pos + 1)
        if end < 0:
            raise TorrentIdentityError("Unterminated bencoded integer")
        number = data[pos + 1 : end]
        if not number:
            raise TorrentIdentityError("Empty bencoded integer")
        try:
            int(number)
        except ValueError as exc:
            raise TorrentIdentityError("Invalid bencoded integer") from exc
        return end + 1
    if token == ord("l"):
        pos += 1
        while True:
            if pos >= len(data):
                raise TorrentIdentityError("Unterminated bencoded list")
            if data[pos] == ord("e"):
                return pos + 1
            pos = _skip_value(data, pos)
    if token == ord("d"):
        pos += 1
        while True:
            if pos >= len(data):
                raise TorrentIdentityError("Unterminated bencoded dictionary")
            if data[pos] == ord("e"):
                return pos + 1
            _, pos = _read_bytes(data, pos)
            pos = _skip_value(data, pos)
    raise TorrentIdentityError("Unknown bencode token")


def _top_level_value_span(data: bytes, key_to_find: bytes) -> tuple[int, int]:
    if not data or data[0] != ord("d"):
        raise TorrentIdentityError("Torrent metadata must be a bencoded dictionary")
    pos = 1
    found: tuple[int, int] | None = None
    while True:
        if pos >= len(data):
            raise TorrentIdentityError("Unterminated torrent dictionary")
        if data[pos] == ord("e"):
            if pos != len(data) - 1:
                # Trailing bytes are not valid torrent metadata; reject rather
                # than calculate an identity from ambiguous input.
                raise TorrentIdentityError("Trailing data after torrent dictionary")
            break
        key, pos = _read_bytes(data, pos)
        value_start = pos
        value_end = _skip_value(data, pos)
        if key == key_to_find:
            if found is not None:
                raise TorrentIdentityError("Duplicate info dictionary")
            found = (value_start, value_end)
        pos = value_end
    if found is None:
        raise TorrentIdentityError("Torrent has no info dictionary")
    return found
