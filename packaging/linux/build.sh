#!/usr/bin/env bash
set -euo pipefail
python -m pip install -e '.[dev]'
python -m pytest
python -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name RD-Desktop \
  --collect-data rdclient \
  'RD Desktop.py'
./dist/RD-Desktop/RD-Desktop --self-test
target="${RD_LINUX_TARGET:-}"
if [[ -n "$target" && ! "$target" =~ ^[a-z0-9][a-z0-9.-]*$ ]]; then
  echo 'RD_LINUX_TARGET must be a distro identifier such as ubuntu-24.04.' >&2
  exit 1
fi
tar -C dist -czf "dist/RD-Desktop-Linux-${target:+$target-}x86_64.tar.gz" RD-Desktop
