"""Write SHA-256 checksums for distributable files in one output directory."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', default='SHA256SUMS.txt')
    args = parser.parse_args()
    if Path(args.output).name != args.output:
        parser.error('--output must be a filename, without directories')
    archives = sorted(path for path in args.directory.iterdir()
                      if path.is_file() and path.suffix in {'.gz', '.zip', '.deb', '.rpm', '.whl'})
    if not archives:
        parser.error('no distributable archives found')
    lines = []
    for path in archives:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        lines.append(f'{digest.hexdigest()}  {path.name}\n')
    output = args.directory / args.output
    output.write_text(''.join(lines), encoding='utf-8', newline='\n')
    print(output)


if __name__ == '__main__':
    main()
