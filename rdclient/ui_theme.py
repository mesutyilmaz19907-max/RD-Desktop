"""Shared color, typography, and spacing tokens for the desktop UI."""
from __future__ import annotations

import os
import base64
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .ui_assets import composite_png, icon_png, opaque_png, rounded_png
from .platform_support import linux_prefers_dark


DARK_COLORS = {
    'bg': '#11151B', 'sidebar': '#0C1016', 'panel': '#191F28',
    'panel_alt': '#202733', 'field': '#12171F', 'border': '#2B3442',
    'text': '#F1F4F8', 'muted': '#96A2B4', 'green': '#9BE3B6',
    'green_button': '#96DDB0', 'green_button_hover': '#ACEBC3',
    'primary_text': '#12281C', 'blue': '#9DBFFE',
    'blue_button': '#242F40', 'blue_button_hover': '#303D52',
    'red': '#F09AA6', 'red_hover': '#F8B5BD',
    'danger_bg': '#2C212B', 'danger_hover': '#3A2934', 'danger_border': '#563641',
    'neutral': '#202733', 'neutral_hover': '#2B3544',
    'selection': '#2B423B', 'nav_active': '#1C3028', 'nav_hover': '#1A202A',
    'disabled': '#1D232D', 'disabled_text': '#98A5B8', 'header': '#0C1016',
}

LIGHT_COLORS = {
    'bg': '#F3F5F8', 'sidebar': '#FCFDFE', 'panel': '#FFFFFF',
    'panel_alt': '#F0F3F7', 'field': '#F8FAFC', 'border': '#D6DDE7',
    'text': '#202B3B', 'muted': '#606F84', 'green': '#28794D',
    'green_button': '#28794D', 'green_button_hover': '#216540',
    'primary_text': '#FFFFFF', 'blue': '#355E9B',
    'blue_button': '#EDF2FA', 'blue_button_hover': '#E2EAF6',
    'red': '#B1344C', 'red_hover': '#95273C',
    'danger_bg': '#FFF5F6', 'danger_hover': '#FBE8EC', 'danger_border': '#EBCAD1',
    'neutral': '#FFFFFF', 'neutral_hover': '#ECF0F5',
    'selection': '#DCEEE3', 'nav_active': '#E6F2EA', 'nav_hover': '#EDF1F6',
    'disabled': '#F0F3F6', 'disabled_text': '#5D6B80', 'header': '#FCFDFE',
}


def system_prefers_dark() -> bool:
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                return int(winreg.QueryValueEx(key, 'AppsUseLightTheme')[0]) == 0
        except (OSError, ValueError):
            return True
    detected = linux_prefers_dark()
    return True if detected is None else detected


IS_DARK = system_prefers_dark()
COLORS = DARK_COLORS if IS_DARK else LIGHT_COLORS
SCALE = 1.0
FONT_FAMILY = 'Segoe UI'
FONT_SEMIBOLD = ''


def px(value: float) -> int:
    return max(1, round(value * SCALE)) if value else 0


def font(size: int = 10, bold: bool = False) -> tuple:
    if bold and FONT_SEMIBOLD:
        return (FONT_SEMIBOLD, size, 'normal')
    return (FONT_FAMILY, size, 'bold' if bold else 'normal')


def configure_theme(root: tk.Tk) -> None:
    global SCALE, FONT_FAMILY, FONT_SEMIBOLD
    SCALE = max(.85, min(3., float(root.tk.call('tk', 'scaling')) / (96 / 72)))
    families = {name.casefold(): name for name in tkfont.families(root)}
    FONT_FAMILY = next((families[name.casefold()] for name in ('Segoe UI', 'DejaVu Sans', 'Helvetica', 'Arial')
                        if name.casefold() in families), str(root.tk.call('font', 'actual', 'TkDefaultFont', '-family')))
    FONT_SEMIBOLD = families.get('segoe ui semibold', '') if FONT_FAMILY.casefold() == 'segoe ui' else ''
    root.option_add('*Font', font())
    root.option_add('*Menu.Font', font(10))
    style = ttk.Style(root)
    style.theme_use('clam')
    c = COLORS
    root.option_add('*Menu.disabledForeground', c['disabled_text'])
    style.configure('.', background=c['bg'], foreground=c['text'], font=font())
    for prefix, surface in (('', 'bg'), ('Panel.', 'panel')):
        style.configure(prefix + 'TFrame', background=c[surface])
        style.configure(prefix + 'TLabel', background=c[surface], foreground=c['text'])
        style.configure(prefix + 'TCheckbutton', background=c[surface], foreground=c['text'], padding=px(3), focuscolor=c[surface])
        style.map(prefix + 'TCheckbutton', background=[('active', c[surface])], foreground=[('disabled', c['disabled_text'])])
    style.configure('Muted.TLabel', background=c['bg'], foreground=c['muted'])
    style.configure('TSeparator', background=c['border'])
    style.configure('TEntry', fieldbackground=c['field'], foreground=c['text'],
                    bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['border'],
                    insertcolor=c['text'], background=c['bg'], padding=(px(10), px(8)), relief='flat')
    style.map('TEntry', fieldbackground=[('readonly', c['field']), ('disabled', c['disabled'])],
              foreground=[('disabled', c['disabled_text'])],
              bordercolor=[('focus', c['blue'])], lightcolor=[('focus', c['blue'])], darkcolor=[('focus', c['blue'])])
    style.configure('Treeview', background=c['panel'], fieldbackground=c['panel'], foreground=c['text'],
                    borderwidth=0, relief='flat', rowheight=px(42), font=font(10))
    style.map('Treeview', background=[('selected', c['selection'])], foreground=[('selected', c['text'])])
    style.configure('Treeview.Heading', background=c['panel_alt'], foreground=c['muted'], relief='flat',
                    borderwidth=0, padding=(px(4), px(12)), font=font(9, True))
    style.map('Treeview.Heading', background=[('active', c['neutral_hover'])], foreground=[('active', c['text'])])
    style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
    style.configure('Horizontal.TProgressbar', background=c['green_button'], troughcolor=c['field'],
                    bordercolor=c['field'], lightcolor=c['green_button'], darkcolor=c['green_button'])
    _configure_inputs(root, style)


def _configure_inputs(root: tk.Tk, style: ttk.Style) -> None:
    """Use native entry/check/menu behavior with the same smooth flat chrome."""
    c = COLORS
    root._rd_field_images = []
    def photo(data: bytes) -> tk.PhotoImage:
        image = tk.PhotoImage(master=root, data=base64.b64encode(data))
        root._rd_field_images.append(image)
        return image
    size = px(38)
    for prefix,surface in (('', 'bg'), ('Panel.', 'panel')):
        field = photo(opaque_png(rounded_png(size,size,px(7),c['field'],c['border']),c[surface]))
        focused = photo(opaque_png(rounded_png(size,size,px(7),c['field'],c['blue'],px(2)),c[surface]))
        disabled = photo(opaque_png(rounded_png(size,size,px(7),c['disabled'],c['border']),c[surface]))
        element='RD.'+prefix+'Entry.field'
        style.element_create(element,'image',field,('disabled',disabled),('focus',focused),border=px(7),sticky='nsew')
        style.layout(prefix+'TEntry',[(element,{'sticky':'nsew','children':[
            ('Entry.padding',{'sticky':'nsew','children':[('Entry.textarea',{'sticky':'nsew'})]})
        ]})])
        style.configure(prefix+'TEntry',padding=(px(5),px(3)),background=c[surface])
    style.element_create('RD.Menu.field','image',field,('focus',focused),border=px(7),sticky='nsew')
    style.layout('Language.TMenubutton',[('RD.Menu.field',{'sticky':'nsew','children':[
        ('Menubutton.padding',{'sticky':'nsew','children':[
            ('Menubutton.indicator',{'side':'right','sticky':''}),
            ('Menubutton.label',{'side':'left','sticky':'nsew'}),
        ]})
    ]})])
    style.configure('Language.TMenubutton',padding=(px(5),px(3)),background=c['panel'],foreground=c['text'],font=font(9),arrowcolor=c['muted'])
    check_size=px(18)
    check=icon_png('check',check_size,c['primary_text'])
    unchecked=photo(rounded_png(check_size,check_size,px(4),c['field'],c['border']))
    checked=photo(composite_png(rounded_png(check_size,check_size,px(4),c['green_button']),check))
    check_focus=photo(composite_png(rounded_png(check_size,check_size,px(4),c['green_button'],c['blue'],px(2)),check))
    empty_focus=photo(rounded_png(check_size,check_size,px(4),c['field'],c['blue'],px(2)))
    style.element_create('RD.Check.indicator','image',unchecked,('selected','focus',check_focus),('selected',checked),('focus',empty_focus),width=px(26),sticky='w')
    layout=[('Checkbutton.padding',{'sticky':'nsew','children':[
        ('RD.Check.indicator',{'side':'left','sticky':''}),
        ('Checkbutton.focus',{'side':'left','sticky':'nsew','children':[('Checkbutton.label',{'sticky':'nsew'})]}),
    ]})]
    style.layout('TCheckbutton',layout)
    style.layout('Panel.TCheckbutton',layout)
