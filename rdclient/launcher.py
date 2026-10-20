from __future__ import annotations

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from .constants import APP_VERSION
from .platform_support import data_dir, ensure_private_dir, ensure_private_file

_LOG_STREAM = None


def configure_logging() -> Path:
    global _LOG_STREAM
    directory = data_dir()
    ensure_private_dir(directory)
    log_file = directory / "rd-desktop.log"
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    ensure_private_file(log_file)
    try:
        _LOG_STREAM = open(log_file, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(_LOG_STREAM, all_threads=True)
    except Exception:
        _LOG_STREAM = None
    logging.info("RD Desktop v%s starting; Python=%s executable=%s", APP_VERSION, sys.version.replace("\n", " "), sys.executable)
    return log_file


def self_test() -> int:
    import tkinter
    import urllib.request
    from .api import RealDebridAPI
    from .config import SecretStore
    assert sys.version_info >= (3, 10)
    assert tkinter.TkVersion >= 8.6
    assert urllib.request is not None
    assert RealDebridAPI is not None
    assert SecretStore is not None
    print("SELF-TEST OK")
    return 0


def main() -> int:
    log_file = configure_logging()
    if "--self-test" in sys.argv:
        return self_test()
    try:
        from .app import run
        return int(run())
    except Exception as exc:
        logging.critical("Startup failure", exc_info=True)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("RD Desktop - Startup error", f"The app could not start.\n\n{exc}\n\nDiagnostic log:\n{log_file}")
            root.destroy()
        except Exception:
            pass
        return 1
