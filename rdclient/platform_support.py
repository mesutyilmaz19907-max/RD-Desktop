from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from .constants import APP_NAME


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    if sys.platform.startswith("linux"):
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base / "rd-desktop"
    raise RuntimeError(f"Unsupported operating system: {sys.platform}")


def data_dir() -> Path:
    if os.name == "nt":
        return config_dir()
    if sys.platform.startswith("linux"):
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        return base / "rd-desktop"
    raise RuntimeError(f"Unsupported operating system: {sys.platform}")


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.chmod(0o700)
        except OSError:
            pass


def ensure_private_file(path: Path) -> None:
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    ensure_private_dir(path.parent)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding=encoding) as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    ensure_private_file(temp)
    os.replace(temp, path)
    ensure_private_file(path)


def open_path(path: str | Path) -> None:
    target = str(Path(path))
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
        return
    if sys.platform.startswith("linux"):
        subprocess.Popen(
            ["xdg-open", target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return
    raise RuntimeError(f"Unsupported operating system: {sys.platform}")


def open_folder_for(path: str | Path) -> None:
    p = Path(path)
    open_path(p if p.is_dir() else p.parent)


def linux_prefers_dark() -> bool | None:
    if not sys.platform.startswith("linux"):
        return None
    probes: Iterable[list[str]] = (
        ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
        ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
    )
    for command in probes:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=1.5, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        value = result.stdout.strip().strip("'").lower()
        if value:
            return "dark" in value
    return None
