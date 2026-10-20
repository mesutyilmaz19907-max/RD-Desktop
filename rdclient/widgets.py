"""Shared, keyboard-accessible desktop controls with smooth PNG chrome."""
from __future__ import annotations

import base64
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from .ui_assets import icon_png, rounded_png
from .ui_theme import COLORS, font, px


def _photo(master: tk.Misc, data: bytes) -> tk.PhotoImage:
    return tk.PhotoImage(master=master, data=base64.b64encode(data))


def icon_image(master: tk.Misc, name: str, size: int = 20, color: str | None = None) -> tk.PhotoImage:
    root = master._root()
    if not hasattr(root, '_rd_icon_images'):
        root._rd_icon_images = {}
    key = (name, size, color or COLORS['muted'])
    if key not in root._rd_icon_images:
        root._rd_icon_images[key] = _photo(root, icon_png(*key))
    return root._rd_icon_images[key]


def _rounded_shape(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs: Any) -> int:
    image = _photo(canvas, rounded_png(max(1, round(x2-x1)), max(1, round(y2-y1)), round(radius),
                   kwargs.pop('fill', ''), kwargs.pop('outline', ''), round(kwargs.pop('width', 1))))
    if not hasattr(canvas, '_rd_surface_images'):
        canvas._rd_surface_images = []
    canvas._rd_surface_images.append(image)
    return int(canvas.create_image(x1, y1, image=image, anchor='nw', tags=kwargs.get('tags', ())))


def _draw_icon(canvas: tk.Canvas, name: str, cx: float, cy: float, color: str, *, scale: float = 1., tag: str = 'icon') -> None:
    canvas.create_image(cx, cy, image=icon_image(canvas, name, max(8, round(24*scale)), color), tags=tag)


def _background(parent: tk.Misc) -> str:
    try:
        return str(parent.cget('background'))
    except tk.TclError:
        return COLORS['bg']


def _button_style(parent: tk.Misc, kind: str) -> str:
    root = parent._root()
    if not hasattr(root, '_rd_button_styles'):
        root._rd_button_styles = {}
    bg = _background(parent)
    key = (kind, bg)
    if key in root._rd_button_styles:
        return root._rd_button_styles[key][0]
    c = COLORS
    face, hover, foreground, border = {
        'primary': (c['green_button'], c['green_button_hover'], c['primary_text'], c['green_button']),
        'secondary': (c['blue_button'], c['blue_button_hover'], c['blue'], c['border']),
        'danger': (c['danger_bg'], c['danger_hover'], c['red'], c['danger_border']),
        'neutral': (c['neutral'], c['neutral_hover'], c['text'], c['border']),
    }.get(kind, (c['neutral'], c['neutral_hover'], c['text'], c['border']))
    style = ttk.Style(root)
    name = f'RD{len(root._rd_button_styles)}.TButton'
    size, radius = px(38), px(7)
    images = [_photo(root, rounded_png(size, size, radius, f, b, px(w))) for f, b, w in (
        (face, border, 1), (hover, border, 1), (hover, c['blue'], 2),
        (face, c['blue'], 2), (c['disabled'], c['border'], 1),
    )]
    element = name + '.surface'
    style.element_create(element, 'image', images[0],
                         ('disabled', images[4]), ('pressed', '!disabled', images[1]),
                         ('active', 'focus', '!disabled', images[2]), ('focus', '!disabled', images[3]),
                         ('active', '!disabled', images[1]), border=px(7), sticky='nsew')
    style.layout(name, [(element, {'sticky': 'nsew', 'children': [
        ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})
    ]})])
    style.configure(name, background=bg, foreground=foreground, font=font(9, True),
                    padding=(px(7), px(3)), anchor='center', width=0)
    style.map(name, foreground=[('disabled', c['disabled_text'])],
              background=[('disabled', bg), ('active', bg), ('pressed', bg)])
    root._rd_button_styles[key] = (name, images, foreground)
    return name


class RoundedButton(ttk.Button):
    """Native ttk interaction with a flat, antialiased rounded surface."""
    def __init__(self, parent: tk.Misc, text: str, command: Callable[[], None], *,
                 kind: str = 'primary', state: str = 'normal', radius: int = 7, icon: str | None = None) -> None:
        self._kind, self._icon = kind, icon
        super().__init__(parent, text=text, command=command, state=state,
                         style=_button_style(parent, kind), takefocus=True, compound='left', cursor='hand2')
        self.bind('<Return>', self._return)
        self._redraw()

    def _return(self, _event: tk.Event) -> str:
        if not self.instate(('disabled',)):
            self.invoke()
        return 'break'

    def _redraw(self) -> None:
        disabled = self.instate(('disabled',))
        foreground = {
            'primary': COLORS['primary_text'], 'secondary': COLORS['blue'], 'danger': COLORS['red'],
        }.get(self._kind, COLORS['text'])
        if self._icon:
            normal = icon_image(self, self._icon, px(18), foreground)
            disabled_image = icon_image(self, self._icon, px(18), COLORS['disabled_text'])
            # A specific disabled image prevents ttk's automatic stippling.
            self._image = (normal, 'disabled', disabled_image)
        else:
            self._image = ''
        super().configure(image=self._image, cursor='arrow' if disabled else 'hand2')

    def configure(self, cnf: Any = None, **kwargs: Any) -> Any:
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        if not kwargs and not isinstance(cnf, dict):
            return super().configure(cnf)
        if 'icon' in kwargs:
            self._icon = kwargs.pop('icon')
        result = super().configure(cnf, **kwargs)
        self._redraw()
        return result

    config = configure


class RoundedPanel(tk.Canvas):
    """Quiet outlined surface; content-sized cards or expanding table shells."""
    def __init__(self, parent: tk.Misc, *, radius: int = 10, padding: int = 16, fit_content: bool = False) -> None:
        self.radius, self.padding, self.fit_content = px(radius), px(padding), fit_content
        super().__init__(parent, bg=_background(parent), highlightthickness=0, bd=0)
        self.inner = tk.Frame(self, bg=COLORS['panel'], bd=0, highlightthickness=0)
        self._window = self.create_window(self.padding, self.padding, anchor='nw', window=self.inner)
        self.bind('<Configure>', self._resize)
        if fit_content:
            self.inner.bind('<Configure>', self._fit)

    def _fit(self, _event: tk.Event | None = None) -> None:
        height = self.inner.winfo_reqheight() + self.padding*2
        if self.winfo_pixels(self.cget('height')) != height:
            self.configure(height=height)

    def _resize(self, _event: tk.Event | None = None) -> None:
        self.delete('panel-shape')
        self._rd_surface_images = []
        w, h = self.winfo_width(), self.winfo_height()
        _rounded_shape(self, 0, 0, w, h, self.radius, fill=COLORS['panel'], outline=COLORS['border'], tags='panel-shape')
        self.tag_lower('panel-shape')
        self.coords(self._window, self.padding, self.padding)
        self.itemconfigure(self._window, width=max(1, w-self.padding*2), height=max(1, h-self.padding*2))


class FlowRow(tk.Frame):
    """An action row that wraps instead of clipping translated button labels."""
    def __init__(self, parent: tk.Misc, **kwargs: Any) -> None:
        super().__init__(parent, bg=_background(parent), **kwargs)
        self.items: list[tk.Widget] = []
        self._pending: str | None = None
        self.bind('<Configure>', self._schedule)

    def add(self, widget: tk.Widget) -> tk.Widget:
        self.items.append(widget)
        widget.grid(row=0, column=len(self.items)-1, sticky='w', padx=(0, px(8)))
        widget.bind('<Configure>', self._schedule, add='+')
        self._schedule()
        return widget

    def _schedule(self, _event: tk.Event | None = None) -> None:
        if self._pending is None:
            self._pending = self.after_idle(self._reflow)

    def _reflow(self, _event: tk.Event | None = None) -> None:
        self._pending = None
        available = self.winfo_width()
        if available <= 1:
            return
        row = column = used = 0
        for widget in self.items:
            width = widget.winfo_reqwidth() + px(8)
            if used and used + width > available:
                row += 1
                column = used = 0
            widget.grid_configure(row=row, column=column, padx=(0, px(8)), pady=(0, px(8) if row else 0))
            column += 1
            used += width

    def destroy(self) -> None:
        if self._pending:
            self.after_cancel(self._pending)
        super().destroy()


class ToggleSwitch(tk.Canvas):
    def __init__(self, parent: tk.Misc, variable: tk.BooleanVar, command: Callable[[], None] | None = None) -> None:
        super().__init__(parent, width=px(44), height=px(28), bg=_background(parent), highlightthickness=0, bd=0, cursor='hand2', takefocus=True)
        self.variable, self.command, self.focused = variable, command, False
        self.bind('<Button-1>', self._click)
        self.bind('<space>', self._toggle)
        self.bind('<Return>', self._toggle)
        self.bind('<FocusIn>', lambda _e: self._focus(True))
        self.bind('<FocusOut>', lambda _e: self._focus(False))
        self._trace = variable.trace_add('write', lambda *_: self._draw())
        self._draw()

    def _focus(self, value: bool) -> None:
        self.focused = value
        self._draw()

    def _click(self, event: tk.Event) -> str:
        self.focus_set()
        return self._toggle(event)

    def _toggle(self, _event: tk.Event | None = None) -> str:
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()
        return 'break'

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete('all')
        self._rd_surface_images = []
        on = self.variable.get()
        track = COLORS['green_button'] if on else COLORS['neutral_hover']
        _rounded_shape(self, px(2), px(3), px(42), px(25), px(11), fill=track, outline=COLORS['blue'] if self.focused else '')
        x = px(24 if on else 4)
        _rounded_shape(self, x, px(5), x+px(18), px(23), px(9), fill='#FFFFFF')

    def destroy(self) -> None:
        self.variable.trace_remove('write', self._trace)
        super().destroy()


class SidebarNavButton(tk.Canvas):
    def __init__(self, parent: tk.Misc, text: str, icon: str, command: Callable[[], None]) -> None:
        super().__init__(parent, height=px(44), bg=COLORS['sidebar'], highlightthickness=0, bd=0, cursor='hand2', takefocus=True)
        self.text, self.icon, self.command = text, icon, command
        self.selected = self.hover = self.focused = False
        self.bind('<Button-1>', lambda _e: self._activate())
        self.bind('<space>', lambda _e: self._activate())
        self.bind('<Return>', lambda _e: self._activate())
        self.bind('<Enter>', lambda _e: self._hover(True))
        self.bind('<Leave>', lambda _e: self._hover(False))
        self.bind('<FocusIn>', lambda _e: self._focus(True))
        self.bind('<FocusOut>', lambda _e: self._focus(False))
        self.bind('<Configure>', lambda _e: self._draw())

    def _activate(self) -> str:
        self.focus_set()
        self.command()
        return 'break'

    def _hover(self, value: bool) -> None:
        self.hover = value
        self._draw()

    def _focus(self, value: bool) -> None:
        self.focused = value
        self._draw()

    def set_selected(self, value: bool) -> None:
        self.selected = value
        self._draw()

    def _draw(self) -> None:
        self.delete('all')
        self._rd_surface_images = []
        w, h = max(1, self.winfo_width()), px(44)
        if self.selected or self.hover or self.focused:
            _rounded_shape(self, 0, px(2), w, h-px(2), px(7), fill=COLORS['nav_active'] if self.selected else COLORS['nav_hover'], outline=COLORS['blue'] if self.focused else '')
        foreground = COLORS['green'] if self.selected else COLORS['text'] if self.hover else COLORS['muted']
        _draw_icon(self, self.icon, px(22), h/2, foreground, scale=px(20)/24)
        self.create_text(px(43), h/2, text=self.text, fill=foreground, anchor='w', font=font(10, self.selected))
        if self.selected:
            _rounded_shape(self, w-px(16), h/2-px(3), w-px(10), h/2+px(3), px(3), fill=COLORS['green'])


class SidebarAccountCard(tk.Canvas):
    def __init__(self, parent: tk.Misc, user_var: tk.StringVar, hint: str, command: Callable[[], None]) -> None:
        super().__init__(parent, height=px(70), bg=COLORS['sidebar'], highlightthickness=0, bd=0, cursor='hand2', takefocus=True)
        self.user_var, self.hint, self.command = user_var, hint, command
        self.hover = self.focused = False
        self.bind('<Enter>', lambda _e: self._hover(True))
        self.bind('<Leave>', lambda _e: self._hover(False))
        self.bind('<Button-1>', lambda _e: self._activate())
        self.bind('<Return>', lambda _e: self._activate())
        self.bind('<space>', lambda _e: self._activate())
        self.bind('<FocusIn>', lambda _e: self._focus(True))
        self.bind('<FocusOut>', lambda _e: self._focus(False))
        self.bind('<Configure>', lambda _e: self._draw())
        self._trace = user_var.trace_add('write', lambda *_: self._draw())

    def _activate(self) -> str:
        self.focus_set()
        self.command()
        return 'break'

    def _hover(self, value: bool) -> None:
        self.hover = value
        self._draw()

    def _focus(self, value: bool) -> None:
        self.focused = value
        self._draw()

    def _draw(self) -> None:
        self.delete('all')
        self._rd_surface_images = []
        w = max(px(180), self.winfo_width())
        _rounded_shape(self, 0, 0, w, px(68), px(8), fill=COLORS['nav_hover'] if self.hover else COLORS['sidebar'], outline=COLORS['blue'] if self.focused else COLORS['border'])
        _rounded_shape(self, px(10), px(15), px(44), px(49), px(9), fill=COLORS['nav_active'])
        _draw_icon(self, 'user', px(27), px(32), COLORS['green'], scale=px(18)/24)
        # Constrain long usernames so they cannot run into the trailing arrow.
        import tkinter.font as tkfont
        measure = tkfont.Font(self, font=font(9, True))
        name = self.user_var.get() or 'Real-Debrid'
        while name and measure.measure(name) > w-px(78):
            name = name[:-2] + '…' if not name.endswith('…') else name[:-2] + '…'
        self.create_text(px(54), px(25), text=name, fill=COLORS['text'], anchor='w', font=font(9, True))
        self.create_text(px(54), px(44), text=self.hint, fill=COLORS['muted'], anchor='w', font=font(8))
        _draw_icon(self, 'chevron', w-px(14), px(33), COLORS['muted'], scale=px(14)/24)

    def destroy(self) -> None:
        self.user_var.trace_remove('write', self._trace)
        super().destroy()
