"""Inert presentation fixtures; never authorize or start a transfer."""
import os
import threading
from types import SimpleNamespace
import tkinter as tk
import pytest

from rdclient import ui_theme
from rdclient.app import RDModernApp
from rdclient.config import PublicConfig


@pytest.fixture
def ui_root():
    if os.name != 'nt' and not os.environ.get('DISPLAY'):
        pytest.skip('A display is required for native Tk interaction tests.')
    root=tk.Tk()
    root.tk.call('tk','scaling',96/72)
    root.geometry('1020x680+0+0')
    ui_theme.configure_theme(root)
    errors=[]
    root.report_callback_exception=lambda typ,exc,tb:errors.append(exc)
    yield root
    root.update()
    root.destroy()
    assert not errors


@pytest.fixture
def ui_app(ui_root):
    app=RDModernApp.__new__(RDModernApp)
    app.root=ui_root
    app.language='en'
    app.store=SimpleNamespace(public=PublicConfig(),save=lambda:None)
    app.api=SimpleNamespace(authenticated=False)
    app.download_jobs={}
    app.download_controls={}
    app.local_status_state={}
    app.download_lock=threading.RLock()
    app.download_wakeup=threading.Event()
    app.download_counter=0
    app.last_unrestricted=[]
    app.torrent_data={}
    app.history_data={}
    app._build_ui()
    ui_root.update()
    return app
