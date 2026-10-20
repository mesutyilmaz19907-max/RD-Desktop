#!/usr/bin/env bash
set -euo pipefail
python -m pip install -e '.[dev]'
python -m pytest
python -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name RD-Desktop \
  --collect-data rdclient \
  'RD Desktop.py'
./dist/RD-Desktop/RD-Desktop --self-test
tar -C dist -czf dist/RD-Desktop-Linux-x86_64.tar.gz RD-Desktop
