"""Inert presentation fixtures; never authorize or start a transfer."""
import os
import threading
from types import SimpleNamespace
import tkinter as tk
import pytest

from rdclient import ui_theme
from rdclient.app import RDModernApp
from rdclient.config import PublicConfig


@pytest.fixture(scope='session')
def ui_session():
    if os.name != 'nt' and not os.environ.get('DISPLAY'):
        pytest.skip('A display is required for native Tk interaction tests.')
    root=tk.Tk()
    root.tk.call('tk','scaling',96/72)
    ui_theme.configure_theme(root)
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def ui_root(ui_session):
    # Keep one Tcl/Tk interpreter alive, with fresh widgets for each test.
    # Repeated interpreter teardown can break Tcl library discovery on Windows.
    root=ui_session
    errors=[]
    root.report_callback_exception=lambda typ,exc,tb:errors.append(exc)
    root.geometry('1020x680+0+0')
    root.deiconify()
    # Finish mapping the owner before tests open transient popups. Windows
    # delivers its initial Configure events after idle layout has completed.
    root.update()
    yield root
    root.update()
    menu=getattr(root,'_rd_context_menu',None)
    if menu is not None:
        menu.close(restore_focus=False)
    grab=root.grab_current()
    if grab is not None:
        grab.grab_release()
    for timer in root.tk.call('after','info'):
        root.after_cancel(timer)
    for widget in root.winfo_children():
        widget.destroy()
    root.withdraw()
    root.update_idletasks()
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
