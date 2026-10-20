"""Native popup interaction tests; commands use inert fixtures."""
from types import SimpleNamespace
import ctypes

import pytest

from rdclient import menus
from rdclient.menus import ContextMenu
from rdclient.ui_theme import COLORS


@pytest.mark.parametrize('accepted', [True, False])
def test_windows_rounding_targets_only_the_popup_and_frees_failed_regions(monkeypatch, accepted):
    calls = []
    class NativeCall:
        def __init__(self, name, result):
            self.name, self.result = name, result
        def __call__(self, *args):
            calls.append((self.name, args))
            return self.result
    user32 = SimpleNamespace(SetWindowRgn=NativeCall('apply', int(accepted)))
    gdi32 = SimpleNamespace(CreateRoundRectRgn=NativeCall('create', 999),
                            DeleteObject=NativeCall('delete', 1))
    monkeypatch.setattr(menus, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user32, gdi32=gdi32), raising=False)
    popup = SimpleNamespace(wm_frame=lambda: '0x42')
    menus._round_windows_window(popup, 240, 364)
    assert ('apply', (66, 999, True)) in calls
    assert any(name == 'delete' for name, _ in calls) is not accepted


def sample_menu(root, hits):
    menu = ContextMenu(root)
    menu.add_command(label='Pause', command=lambda: hits.append('pause'), icon='pause')
    menu.add_command(label='Resume', command=lambda: hits.append('resume'), icon='resume', state='disabled')
    menu.add_separator()
    menu.add_command(label='Copy path', command=lambda: hits.append('copy'), icon='copy')
    menu.popup(100, 100, keyboard=True)
    root.update()
    return menu


def test_keyboard_skips_inactive_rows_and_separators(ui_root):
    hits = []
    menu = sample_menu(ui_root, hits)
    assert menu._active_index == 0
    menu.event_generate('<Down>')
    ui_root.update()
    assert menu._active_index == 3
    menu.event_generate('<Down>')
    ui_root.update()
    assert menu._active_index == 0
    menu.event_generate('<End>')
    menu.event_generate('<Return>')
    ui_root.update()
    assert hits == ['copy']
    assert not menu.winfo_exists()
    assert ui_root.grab_current() is None


def test_disabled_mouse_rows_stay_readable_and_do_not_activate(ui_root):
    hits = []
    menu = sample_menu(ui_root, hits)
    top, bottom = menu._bounds[1]
    y = (top + bottom)//2
    for event in ('<Motion>', '<ButtonPress-1>', '<ButtonRelease-1>'):
        menu.canvas.event_generate(event, x=30, y=y,
                                   rootx=menu.winfo_rootx()+30, rooty=menu.winfo_rooty()+y)
        ui_root.update()
    assert menu.canvas.itemcget('item-1', 'fill') == COLORS['disabled_text']
    assert menu._active_index is None
    assert hits == [] and menu.winfo_exists()
    menu.close()


def test_mouse_action_closes_the_popup_before_invocation(ui_root):
    order = []
    menu = ContextMenu(ui_root)
    menu.add_command(label='Copy', command=lambda: order.append((menu.winfo_exists(), ui_root.grab_current())))
    menu.popup(100, 100)
    ui_root.update()
    y = sum(menu._bounds[0])//2
    for event in ('<ButtonPress-1>', '<ButtonRelease-1>'):
        menu.canvas.event_generate(event, x=30, y=y,
                                   rootx=menu.winfo_rootx()+30, rooty=menu.winfo_rooty()+y)
        ui_root.update()
    assert order == [(0, None)]


def test_escape_and_outside_click_release_the_grab(ui_root):
    hits = []
    menu = sample_menu(ui_root, hits)
    menu.event_generate('<Escape>')
    ui_root.update()
    assert not menu.winfo_exists() and ui_root.grab_current() is None
    menu = sample_menu(ui_root, hits)
    menu.event_generate('<ButtonPress-1>', x=-10, y=-10,
                        rootx=menu.winfo_rootx()-10, rooty=menu.winfo_rooty()-10)
    ui_root.update()
    assert not menu.winfo_exists() and ui_root.grab_current() is None
    assert hits == []


def test_focus_loss_dismisses_without_invoking_an_action(ui_root):
    hits = []
    menu = sample_menu(ui_root, hits)
    ui_root.focus_force()
    ui_root.update()
    assert not menu.winfo_exists()
    assert hits == [] and ui_root.grab_current() is None


def test_replacement_and_repeated_close_do_not_leave_popup_bindings(ui_root):
    hits = []
    original = ui_root.bind('<Configure>')
    first = sample_menu(ui_root, hits)
    second = sample_menu(ui_root, hits)
    assert not first.winfo_exists()
    assert ui_root.grab_current() is second
    second.close()
    second.close()
    ui_root.update()
    assert getattr(ui_root, '_rd_context_menu', None) is None
    assert ui_root.bind('<Configure>') == original


def test_popup_stays_inside_the_available_work_area(ui_root, monkeypatch):
    monkeypatch.setattr(menus, '_work_area', lambda *args: (0, 0, 600, 400))
    menu = ContextMenu(ui_root)
    menu.add_command(label='Copy', command=lambda: None, icon='copy')
    menu.popup(595, 395)
    ui_root.update()
    assert menu.winfo_rootx() >= 0 and menu.winfo_rooty() >= 0
    assert menu.winfo_rootx()+menu.winfo_width() <= 600
    assert menu.winfo_rooty()+menu.winfo_height() <= 400
    menu.close()


def test_popup_restores_an_existing_local_grab(ui_root):
    ui_root.update()
    ui_root.grab_set()
    menu = sample_menu(ui_root, [])
    assert ui_root.grab_current() is menu
    menu.close()
    assert ui_root.grab_current() is ui_root
    ui_root.grab_release()


def add_local_row(client, status):
    client.nb.select(2)
    client.download_jobs[1] = {'id': 1, 'status': status, 'dest': r'C:\Demo\sample.bin'}
    client.local_tree.insert('', 'end', iid='1', values=('Sample', status, '0%', '', '', '', r'C:\Demo\sample.bin'))
    client.local_tree.selection_set('1')
    client.local_tree.focus('1')
    client.root.update()


def test_download_context_matches_the_toolbar_action_states(ui_app):
    add_local_row(ui_app, 'Downloading')
    ui_app._keyboard_context(ui_app.local_tree, ui_app._local_context)
    ui_app.root.update()
    menu = ui_app.root._rd_context_menu
    actions = {item.label: item.enabled for item in menu.items if item}
    assert actions[ui_app.t('pause')]
    assert actions[ui_app.t('cancel')]
    assert not actions[ui_app.t('resume')]
    assert not actions[ui_app.t('remove')]
    assert not actions[ui_app.t('retry')]
    assert not actions[ui_app.t('open_file')]
    menu.close()


def test_missing_download_uses_one_redownload_action(ui_app):
    add_local_row(ui_app, 'Missing')
    ui_app._keyboard_context(ui_app.local_tree, ui_app._local_context)
    ui_app.root.update()
    menu = ui_app.root._rd_context_menu
    actions = {item.label: item.enabled for item in menu.items if item}
    assert actions[ui_app.t('redownload')]
    assert ui_app.t('retry') not in actions
    assert actions[ui_app.t('locate_file')]
    assert not actions[ui_app.t('open_file')]
    menu.close()


def test_torrent_context_preserves_multiple_selected_rows(ui_app):
    ui_app.nb.select(1)
    for iid in ('1', '2'):
        ui_app.torrent_tree.insert('', 'end', iid=iid, values=('Sample', 'Ready', '100%', '', '', '', ''))
    ui_app.torrent_tree.selection_set('1', '2')
    ui_app.torrent_tree.focus('1')
    ui_app.root.update()
    ui_app._keyboard_context(ui_app.torrent_tree, ui_app._torrent_context)
    ui_app.root.update()
    menu = ui_app.root._rd_context_menu
    assert ui_app.torrent_tree.selection() == ('1', '2')
    choose = next(item for item in menu.items if item and item.label == ui_app.t('choose_files'))
    assert not choose.enabled
    menu.close()


def test_blank_right_click_clears_selection_and_does_not_open_a_menu(ui_app):
    add_local_row(ui_app, 'Paused')
    ui_app._local_context(SimpleNamespace(y=500, x_root=500, y_root=600))
    assert ui_app.local_tree.selection() == ()
    assert getattr(ui_app.root, '_rd_context_menu', None) is None
