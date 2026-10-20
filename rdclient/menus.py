"""Themed context menus with readable inactive rows and keyboard navigation."""
from __future__ import annotations

from dataclasses import dataclass
import os
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from .ui_theme import COLORS, font, px
from .widgets import _draw_icon, _rounded_shape


@dataclass(frozen=True)
class MenuAction:
    label: str
    command: Callable[[], None]
    icon: str | None = None
    enabled: bool = True
    danger: bool = False


def _work_area(window: tk.Misc, x: int, y: int) -> tuple[int, int, int, int]:
    """Use the clicked monitor's work area, including negative monitor origins."""
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            class MonitorInfo(ctypes.Structure):
                _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                            ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]
            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom
        except (AttributeError, OSError, ValueError):
            pass
    left, top = window.winfo_vrootx(), window.winfo_vrooty()
    return left, top, left + window.winfo_vrootwidth(), top + window.winfo_vrootheight()


def _round_windows_window(window: tk.Toplevel, width: int, height: int) -> None:
    if os.name != 'nt':
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
        user32.SetWindowRgn.restype = ctypes.c_int
        gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteObject.restype = wintypes.BOOL
        # Tk identifies this popup's outer HWND directly. GetParent on a popup
        # may identify its owner instead, which must never receive this region.
        handle = int(str(window.wm_frame()), 0)
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, px(20), px(20))
        if region and not user32.SetWindowRgn(handle, region, True):
            gdi32.DeleteObject(region)
        # Windows owns a successfully applied region and frees it with the window.
    except (AttributeError, OSError, ValueError, tk.TclError):
        pass


class ContextMenu(tk.Toplevel):
    """A compact popup; unavailable actions never highlight or activate."""
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=COLORS['bg'], bd=0)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(parent.winfo_toplevel())
        self._owner = parent.winfo_toplevel()
        self._root_window = parent._root()
        self.items: list[MenuAction | None] = []
        self._bounds: dict[int, tuple[int, int]] = {}
        self._active_index: int | None = None
        self._pressed_index: int | None = None
        self._keyboard = False
        self._closed = False
        self._focus_check: str | None = None
        self._old_focus: tk.Misc | None = None
        self._old_grab: tk.Misc | None = None
        self._owner_bindings: list[tuple[str, str]] = []
        self.canvas = tk.Canvas(self, bg=COLORS['bg'], bd=0, highlightthickness=0, takefocus=False)
        self.canvas.pack(fill='both', expand=True)
        self.bind('<Motion>', self._motion)
        self.bind('<Leave>', self._leave)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<ButtonPress-3>', self._right_press)
        self.bind('<Up>', lambda _e: self._move(-1))
        self.bind('<Down>', lambda _e: self._move(1))
        self.bind('<Home>', lambda _e: self._edge(False))
        self.bind('<End>', lambda _e: self._edge(True))
        self.bind('<Return>', lambda _e: self._activate())
        self.bind('<space>', lambda _e: self._activate())
        self.bind('<Escape>', lambda _e: self._dismiss())
        self.bind('<Tab>', lambda _e: self._dismiss())
        self.bind('<FocusOut>', self._focus_out)
        self.bind('<Destroy>', self._destroyed)
        self.protocol('WM_DELETE_WINDOW', self.close)
        try:
            self.attributes('-type', 'popup_menu')
        except tk.TclError:
            pass

    def add_command(self, *, label: str, command: Callable[[], None],
                    icon: str | None = None, state: str = 'normal', kind: str = 'neutral') -> None:
        self.items.append(MenuAction(label, command, icon, state != 'disabled', kind == 'danger'))

    def add_separator(self) -> None:
        if self.items and self.items[-1] is not None:
            self.items.append(None)

    def popup(self, x: int, y: int, *, keyboard: bool = False) -> None:
        existing = getattr(self._root_window, '_rd_context_menu', None)
        if existing is not None and existing is not self:
            existing.close(restore_focus=False)
        self._root_window._rd_context_menu = self
        self._old_focus = self.focus_get()
        self._old_grab = self.grab_current()
        while self.items and self.items[-1] is None:
            self.items.pop()
        metrics = tkfont.Font(self, font=font(10))
        width = max(px(240), max((metrics.measure(item.label) for item in self.items if item), default=0) + px(68))
        top = px(8)
        for index, item in enumerate(self.items):
            height = px(36) if item else px(12)
            self._bounds[index] = (top, top + height)
            top += height
        self._width, self._height = width, top + px(8)
        left, top, right, bottom = _work_area(self, x, y)
        x = max(left, min(x, right - width))
        y = max(top, min(y, bottom - self._height))
        self.geometry(f'{width}x{self._height}+{x}+{y}')
        self.canvas.configure(width=width, height=self._height)
        self._keyboard = keyboard
        if keyboard:
            self._active_index = next(iter(self._enabled()), None)
        self._draw()
        self.deiconify()
        self.lift()
        self.update_idletasks()
        _round_windows_window(self, width, self._height)
        self.grab_set()
        self.focus_force()
        for sequence in ('<Configure>', '<Unmap>', '<Destroy>'):
            binding = self._owner.bind(sequence, self._owner_changed, add='+')
            self._owner_bindings.append((sequence, binding))

    def _draw(self) -> None:
        self.canvas.delete('all')
        self.canvas._rd_surface_images = []
        _rounded_shape(self.canvas, 0, 0, self._width, self._height, px(10),
                       fill=COLORS['panel_alt'], outline=COLORS['border'])
        for index, item in enumerate(self.items):
            top, bottom = self._bounds[index]
            cy = (top + bottom) / 2
            if item is None:
                self.canvas.create_line(px(14), cy, self._width-px(14), cy,
                                        fill=COLORS['border'], width=px(1))
                continue
            if index == self._active_index and item.enabled:
                _rounded_shape(self.canvas, px(6), top, self._width-px(6), bottom, px(6),
                               fill=COLORS['danger_hover'] if item.danger else COLORS['neutral_hover'],
                               outline=COLORS['blue'] if self._keyboard else '')
            foreground = COLORS['disabled_text'] if not item.enabled else COLORS['red'] if item.danger else COLORS['text']
            if item.icon:
                _draw_icon(self.canvas, item.icon, px(24), cy, foreground, scale=px(18)/24)
            self.canvas.create_text(px(46), cy, text=item.label, anchor='w',
                                    font=font(10), fill=foreground, tags=f'item-{index}')

    def _enabled(self) -> list[int]:
        return [index for index, item in enumerate(self.items) if item is not None and item.enabled]

    def _index_at(self, event: tk.Event) -> int | None:
        x, y = event.x_root-self.winfo_rootx(), event.y_root-self.winfo_rooty()
        if not px(6) <= x < self._width-px(6):
            return None
        return next((index for index, (top, bottom) in self._bounds.items()
                     if top <= y < bottom and self.items[index] is not None), None)

    def _select(self, index: int | None, *, keyboard: bool = False) -> None:
        if index is not None and not self.items[index].enabled:
            index = None
        changed = index != self._active_index or keyboard != self._keyboard
        self._keyboard = keyboard
        if changed:
            self._active_index = index
            self._draw()
        self.canvas.configure(cursor='hand2' if index is not None else 'arrow')

    def _motion(self, event: tk.Event) -> None:
        self._select(self._index_at(event))

    def _leave(self, _event: tk.Event) -> None:
        if not self._keyboard:
            self._select(None)

    def _press(self, event: tk.Event) -> str:
        if not self._inside(event):
            return self._dismiss()
        self._pressed_index = self._index_at(event)
        return 'break'

    def _release(self, event: tk.Event) -> str:
        index = self._index_at(event)
        if index is not None and index == self._pressed_index:
            self.invoke(index)
        self._pressed_index = None
        return 'break'

    def _inside(self, event: tk.Event) -> bool:
        return (self.winfo_rootx() <= event.x_root < self.winfo_rootx()+self._width
                and self.winfo_rooty() <= event.y_root < self.winfo_rooty()+self._height)

    def _right_press(self, event: tk.Event) -> str:
        return 'break' if self._inside(event) else self._dismiss()

    def _move(self, step: int) -> str:
        enabled = self._enabled()
        if enabled:
            index = enabled.index(self._active_index) if self._active_index in enabled else (-1 if step > 0 else 0)
            self._select(enabled[(index + step) % len(enabled)], keyboard=True)
        return 'break'

    def _edge(self, last: bool) -> str:
        enabled = self._enabled()
        if enabled:
            self._select(enabled[-1 if last else 0], keyboard=True)
        return 'break'

    def _activate(self) -> str:
        if self._active_index is not None:
            self.invoke(self._active_index)
        return 'break'

    def invoke(self, index: int) -> None:
        item = self.items[index]
        if item is None or not item.enabled or self._closed:
            return
        self.close()
        item.command()

    def _dismiss(self) -> str:
        self.close()
        return 'break'

    def _focus_out(self, _event: tk.Event) -> None:
        if self._focus_check is None and not self._closed:
            self._focus_check = self.after_idle(self._check_focus)

    def _check_focus(self) -> None:
        self._focus_check = None
        if not self._closed and self.focus_get() is not self:
            self.close(restore_focus=False)

    def _owner_changed(self, event: tk.Event) -> None:
        if event.widget is self._owner:
            self.close(restore_focus=False)

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self and not self._closed:
            self.close(restore_focus=False)

    def close(self, *, restore_focus: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        if getattr(self._root_window, '_rd_context_menu', None) is self:
            self._root_window._rd_context_menu = None
        try:
            if self._focus_check is not None:
                self.after_cancel(self._focus_check)
            if self.grab_current() is self:
                self.grab_release()
            for sequence, binding in self._owner_bindings:
                self._owner.unbind(sequence, binding)
            if self._old_grab is not None and self._old_grab.winfo_exists():
                self._old_grab.grab_set()
            if restore_focus:
                target = self._old_focus or self.master
                if target.winfo_exists():
                    target.focus_set()
        except tk.TclError:
            pass
        if self.winfo_exists():
            super().destroy()

    def destroy(self) -> None:
        self.close(restore_focus=False)
