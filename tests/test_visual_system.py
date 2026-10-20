import struct
from tkinter import ttk
import tkinter as tk

from rdclient.ui_assets import _masks, _pixels, icon_png, rounded_png
from rdclient.ui_theme import DARK_COLORS, LIGHT_COLORS
from rdclient.widgets import FlowRow, RoundedButton, ToggleSwitch


def test_surfaces_have_smooth_transparent_corners():
    width,height,rows=_pixels(rounded_png(100,38,7,'#96DDB0','#2B3442'))
    assert (width,height)==(100,38)
    assert rows[0][3]==0
    assert rows[height//2][width//2*4+3]==255
    assert any(0<row[x]<255 for row in rows[:7] for x in range(3,len(row),4))


def test_bundled_icons_scale_to_windows_display_sizes():
    for name in _masks()['icons']:
        for size in (16,18,20,24,30,40):
            png=icon_png(name,size,'#96DDB0')
            assert struct.unpack('!2I',png[16:24])==(size,size)
            _,_,rows=_pixels(png)
            assert any(row[x] for row in rows for x in range(3,len(row),4))


def _contrast(a,b):
    def luminance(color):
        values=[int(color[i:i+2],16)/255 for i in (1,3,5)]
        values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(v*w for v,w in zip(values,(.2126,.7152,.0722)))
    low,high=sorted((luminance(a),luminance(b)))
    return (high+.05)/(low+.05)


def test_both_themes_keep_action_and_body_text_readable():
    for c in (DARK_COLORS,LIGHT_COLORS):
        for foreground,background in (('text','panel'),('muted','panel'),('primary_text','green_button'),('red','danger_bg'),('disabled_text','disabled'),('disabled_text','panel_alt')):
            assert _contrast(c[foreground],c[background])>=4.5


def test_buttons_preserve_native_invocation_and_disabled_state(ui_root):
    hits=[]
    button=RoundedButton(ui_root,'Download',lambda:hits.append(True),icon='download')
    button.pack()
    ui_root.update()
    assert isinstance(button,ttk.Button)
    button.invoke()
    button.configure(state='disabled')
    button.invoke()
    assert hits==[True]
    button.configure(state='normal')
    ui_root.focus_force()
    button.focus_set()
    button.event_generate('<KeyPress-Return>')
    ui_root.update()
    assert hits==[True,True]


def test_buttons_resize_when_their_label_changes(ui_root):
    button=RoundedButton(ui_root,'Retry',lambda:None,icon='refresh')
    button.pack()
    ui_root.update()
    first=button.winfo_reqwidth()
    button.configure(text='Télécharger les fichiers sélectionnés')
    ui_root.update()
    assert button.winfo_reqwidth()>first


def test_toggle_supports_keyboard_and_external_variable_updates(ui_root):
    var=tk.BooleanVar(ui_root,value=False)
    toggle=ToggleSwitch(ui_root,var)
    toggle.pack()
    ui_root.update()
    ui_root.focus_force()
    toggle.focus_set()
    toggle.event_generate('<KeyPress-space>')
    ui_root.update()
    assert var.get()
    var.set(False)
    ui_root.update()
    assert not var.get()


def test_actions_wrap_inside_narrow_rows(ui_root):
    row=FlowRow(ui_root)
    row.place(x=0,y=0,width=230,height=180)
    for label in ('Upload torrents','Download selected','Choose files'):
        row.add(RoundedButton(row,label,lambda:None,icon='download'))
    ui_root.update()
    assert len({int(item.grid_info()['row']) for item in row.items})>1
    assert all(item.winfo_x()+item.winfo_width()<=row.winfo_width() for item in row.items)


def test_action_rows_reflow_after_dynamic_label_changes(ui_root):
    row=FlowRow(ui_root)
    row.place(x=0,y=0,width=230,height=180)
    first=RoundedButton(row,'Retry',lambda:None,icon='refresh')
    second=RoundedButton(row,'Pause',lambda:None,icon='pause')
    row.add(first)
    row.add(second)
    ui_root.update()
    assert int(second.grid_info()['row'])==0
    first.configure(text='Download selection')
    ui_root.update()
    assert int(second.grid_info()['row'])==1


def test_empty_state_follows_real_table_contents(ui_app):
    tree=ui_app.torrent_tree
    ui_app.nb.select(1)
    ui_app.root.update()
    assert tree._rd_empty.winfo_ismapped()
    tree.insert('','end',iid='sample',values=('Sample file','Ready','100%','1 GB','','',''))
    ui_app.root.update()
    assert not tree._rd_empty.winfo_ismapped()
    tree.delete('sample')
    ui_app.root.update()
    assert tree._rd_empty.winfo_ismapped()


def test_number_stepper_keeps_safe_bounds_and_live_validation(ui_app):
    stepper=ui_app.download_limit_stepper
    warnings=[]
    stepper.invalid_command=lambda:warnings.append(True)
    stepper.var.set('9')
    assert warnings
    assert stepper.commit()==8
    stepper._step(1)
    assert stepper.var.get()=='8'
    stepper.var.set('0')
    assert stepper.commit()==1
