"""Extract the selected public release's notes from CHANGELOG.md."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--changelog', type=Path, default=Path('CHANGELOG.md'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    version = args.tag.removeprefix('v')
    selected = False
    notes = []
    for line in args.changelog.read_text(encoding='utf-8').splitlines():
        if line.startswith('## '):
            if selected:
                break
            heading_version = line[3:].split(maxsplit=1)[0].strip('[]')
            selected = heading_version == version
        elif selected:
            notes.append(line)
    body = '\n'.join(notes).strip()
    if not body:
        parser.error(f'no release notes found for {args.tag}')
    args.output.write_text(body + '\n', encoding='utf-8', newline='\n')
    print(args.output)


if __name__ == '__main__':
    main()
