"""Antialiased UI assets, rendered with the standard library at runtime.

Icons are compiled Lucide monochrome masks; Tk receives PNGs tinted to the current
theme. Rounded surfaces use pixel coverage rather than Tk's polygon splines.
No Pillow, icon fonts, or external GUI framework is required by the app.
"""
from __future__ import annotations

import base64
from functools import lru_cache
import json
import math
from pathlib import Path
import struct
import zlib


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)


def rgba_png(width: int, height: int, rows: list[bytes]) -> bytes:
    header = struct.pack('!2I5B', width, height, 8, 6, 0, 0, 0)
    pixels = b''.join(b'\0' + row for row in rows)
    return b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', header) + _chunk(b'IDAT', zlib.compress(pixels)) + _chunk(b'IEND', b'')


def _pixels(png: bytes) -> tuple[int, int, list[bytes]]:
    """Decode our own unfiltered RGBA output for small control composites."""
    width, height = struct.unpack('!2I', png[16:24])
    offset, compressed = 8, bytearray()
    while offset < len(png):
        length = struct.unpack('!I', png[offset:offset+4])[0]
        if png[offset+4:offset+8] == b'IDAT':
            compressed.extend(png[offset+8:offset+8+length])
        offset += length + 12
    raw = zlib.decompress(compressed)
    return width, height, [raw[y*(width*4+1)+1:(y+1)*(width*4+1)] for y in range(height)]


def composite_png(base: bytes, overlay: bytes) -> bytes:
    width, height, rows = _pixels(base)
    ow, oh, source = _pixels(overlay)
    output = []
    for y, original in enumerate(rows):
        row = bytearray(original)
        if y < oh:
            for x in range(min(width, ow)):
                pos = x*4
                alpha = source[y][pos+3] / 255
                for channel in range(3):
                    row[pos+channel] = round(source[y][pos+channel] * alpha + row[pos+channel] * (1-alpha))
                row[pos+3] = round(255*alpha + row[pos+3]*(1-alpha))
        output.append(bytes(row))
    return rgba_png(width, height, output)


def opaque_png(png: bytes, background: str) -> bytes:
    """Precompose entry corners: Tk's entry window can otherwise show white."""
    width, height, rows = _pixels(png)
    color = _rgb(background)
    output = []
    for original in rows:
        row = bytearray(original)
        for x in range(width):
            pos = x*4
            alpha = row[pos+3]/255
            if alpha < 1:
                for channel in range(3):
                    row[pos+channel] = round(row[pos+channel]*alpha + color[channel]*(1-alpha))
                row[pos+3] = 255
        output.append(bytes(row))
    return rgba_png(width, height, output)


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


@lru_cache(maxsize=128)
def rounded_png(width: int, height: int, radius: int, fill: str, border: str = '', border_width: int = 1) -> bytes:
    """RGBA rounded rectangle with smooth coverage along the corner edges."""
    width, height = max(1, width), max(1, height)
    radius = max(0, min(radius, width // 2, height // 2))
    bw = max(0, border_width) if border else 0
    face = _rgb(fill) if fill else (0, 0, 0)
    edge = _rgb(border) if border else face
    interior = bytes((*face, 255 if fill else 0))
    rows = []
    for y in range(height):
        ey = min(y, height - 1 - y)
        row = bytearray(interior * width)
        if bw and ey < bw:
            row[:] = bytes((*edge, 255)) * width
        elif bw:
            row[:bw*4] = bytes((*edge, 255)) * min(bw, width)
            row[-bw*4:] = bytes((*edge, 255)) * min(bw, width)
        if ey < radius:
            for x in range(radius):
                distance = math.hypot(radius - x - .5, radius - ey - .5)
                outer = max(0., min(1., radius + .5 - distance))
                inner = max(0., min(1., radius - bw + .5 - distance)) if fill else 0.
                coverage = outer if (fill or bw) else 0.
                if not fill:
                    inner_edge = max(0., min(1., radius - bw + .5 - distance))
                    coverage = max(0., outer - inner_edge)
                if coverage:
                    ratio = min(1., inner / coverage) if fill else 0.
                    pixel = bytes((*[round(edge[i] + (face[i] - edge[i]) * ratio) for i in range(3)], round(255 * coverage)))
                else:
                    pixel = b'\0\0\0\0'
                row[x*4:(x+1)*4] = pixel
                mirror = width - 1 - x
                row[mirror*4:(mirror+1)*4] = pixel
        rows.append(bytes(row))
    return rgba_png(width, height, rows)


ALIASES = {
    'account': 'user', 'unrestrict': 'link', 'torrent': 'magnet',
    'downloads': 'download', 'clock': 'history', 'gear': 'settings',
    'retry': 'refresh', 'add': 'plus', 'choose': 'files', 'direct': 'bolt',
    'delete': 'trash', 'remove': 'trash', 'resume': 'play', 'close': 'cancel',
    'locate': 'folder', 'arrow': 'chevron',
}


@lru_cache(maxsize=1)
def _masks() -> dict:
    path = Path(__file__).resolve().parent / 'assets' / 'ui-icons.json'
    return json.loads(path.read_text(encoding='utf-8'))


@lru_cache(maxsize=256)
def icon_png(name: str, size: int, color: str) -> bytes:
    data = _masks()
    source_size = data['size']
    name = ALIASES.get(name.lower(), name.lower())
    mask = zlib.decompress(base64.b64decode(data['icons'].get(name, data['icons']['files'])))
    size = max(8, min(160, size))
    rgb = _rgb(color)
    # Area sampling preserves the stroke weight at fractional Windows scales.
    rows = []
    for y in range(size):
        row = bytearray()
        sy1, sy2 = y * source_size / size, (y+1) * source_size / size
        for x in range(size):
            sx1, sx2 = x * source_size / size, (x+1) * source_size / size
            total = 0.
            for yy in range(int(sy1), min(source_size, math.ceil(sy2))):
                yw = min(sy2, yy+1) - max(sy1, yy)
                for xx in range(int(sx1), min(source_size, math.ceil(sx2))):
                    xw = min(sx2, xx+1) - max(sx1, xx)
                    total += mask[yy*source_size+xx] * xw * yw
            row.extend((*rgb, round(total / ((sx2-sx1)*(sy2-sy1)))))
        rows.append(bytes(row))
    return rgba_png(size, size, rows)
