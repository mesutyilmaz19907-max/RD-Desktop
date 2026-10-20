"""Rebuild UI masks from the bundled Lucide SVG sources.

Developer-only dependencies: Pillow and CairoSVG. The shipped application
reads these generated masks using Python's standard library.
All icons share a 24 px grid, a 1.75 px stroke, and rounded caps and joins.
The complete Lucide/Feather license is in assets/icons/LICENSE.txt.
"""
import base64
from io import BytesIO
import json
from pathlib import Path
import zlib

import cairosvg
from PIL import Image


ICON_SOURCES = {
    'user': 'user-round',
    'link': 'link',
    'magnet': 'magnet',
    'download': 'download',
    'upload': 'upload',
    'history': 'history',
    'settings': 'sliders-horizontal',
    'refresh': 'refresh-cw',
    'plus': 'plus',
    'files': 'file-text',
    'bolt': 'zap',
    'trash': 'trash-2',
    'pause': 'pause',
    'play': 'play',
    'cancel': 'x',
    'folder': 'folder',
    'chevron': 'chevron-right',
    'check': 'check',
    'chevron_up': 'chevron-up',
    'chevron_down': 'chevron-down',
    'inbox': 'inbox',
    'copy': 'copy',
}


def main():
    project = Path(__file__).resolve().parent.parent
    icons = {}
    for name, source in ICON_SOURCES.items():
        svg = (project / 'assets' / 'icons' / f'{source}.svg').read_text(encoding='utf-8')
        svg = svg.replace('currentColor', '#FFFFFF').replace('stroke-width="2"', 'stroke-width="1.75"')
        rendered = cairosvg.svg2png(bytestring=svg.encode('utf-8'), output_width=192, output_height=192)
        with Image.open(BytesIO(rendered)) as image:
            mask = image.getchannel('A').resize((96, 96), Image.Resampling.LANCZOS)
        icons[name] = base64.b64encode(zlib.compress(mask.tobytes(), 9)).decode('ascii')

    target = project / 'assets' / 'ui-icons.json'
    target.write_text(json.dumps({'size': 96, 'icons': icons}, separators=(',', ':')), encoding='utf-8')
    print(f'Built {len(icons)} icons: {target}')


if __name__ == '__main__':
    main()
