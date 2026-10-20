from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from .api import RealDebridAPI, RealDebridError
from .config import CONFIG_DIR, SecretStore
from .constants import APP_VERSION, MAX_SAFE_SIMULTANEOUS_DOWNLOADS
from .downloads import DownloadJobStore, download_file, reconcile_job
from .platform_support import data_dir, open_folder_for, open_path
from .i18n import LANGUAGE_OPTIONS, month_abbr, normalize_language, tr
from .menus import ContextMenu
from .torrent_identity import item_info_hash, normalize_info_hash


from . import ui_theme as theme
from .ui_theme import COLORS, IS_DARK
from .widgets import (
    FlowRow, RoundedButton, RoundedPanel, SidebarAccountCard, SidebarNavButton,
    ToggleSwitch, _draw_icon, _rounded_shape, icon_image,
)

def apply_windows_titlebar(window: tk.Misc, dark: bool = IS_DARK) -> None:
    """Ask Windows 10/11 to match the native title bar to the application theme."""
    if os.name != "nt":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        enabled = ctypes.c_int(1 if dark else 0)
        # 20 is current; 19 is used by some older Windows 10 builds.
        for attribute in (20, 19):
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
                )
                break
            except Exception:
                continue
    except Exception:
        pass


def style_text_widget(widget: tk.Text) -> tk.Text:
    widget.configure(
        bg=COLORS["field"],
        fg=COLORS["text"],
        insertbackground=COLORS["text"],
        selectbackground=COLORS["selection"],
        selectforeground="#FFFFFF" if IS_DARK else COLORS["text"],
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=COLORS["border"],
        highlightcolor=COLORS["blue"],
        padx=theme.px(12),
        pady=theme.px(10),
        font=theme.font(10),
    )
    return widget


def _shade_color(hex_color: str, factor: float) -> str:
    """Lighten (>1) or darken (<1) a #RRGGBB color."""
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return hex_color
    channels = [int(value[i : i + 2], 16) for i in (0, 2, 4)]
    if factor >= 1:
        channels = [round(c + (255 - c) * min(1.0, factor - 1.0)) for c in channels]
    else:
        channels = [round(c * max(0.0, factor)) for c in channels]
    return "#" + "".join(f"{max(0, min(255, c)):02X}" for c in channels)




class SoftTab(tk.Canvas):
    """A softer, slightly rounded tab without the old beveled ttk look."""

    def __init__(self, parent: tk.Misc, text: str, command: Callable[[], None]) -> None:
        self._text = text
        self._command = command
        self._selected = False
        self._hover = False
        self._font = tkfont.Font(family="Segoe UI Semibold", size=9)
        width = max(92, self._font.measure(text) + 34)
        super().__init__(parent, width=width, height=37, bg=COLORS["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", lambda _e: self._command())
        self.bind("<Configure>", lambda _e: self._redraw())
        self._redraw()

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._redraw()

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        self._rd_surface_images = []
        w = max(1, self.winfo_width() or int(self.cget("width")))
        h = max(1, self.winfo_height() or int(self.cget("height")))
        if self._selected:
            fill = COLORS["panel"]
            fg = COLORS["text"]
        elif self._hover:
            fill = _shade_color(COLORS["panel_alt"], 1.12 if IS_DARK else 0.96)
            fg = COLORS["text"]
        else:
            fill = COLORS["panel_alt"]
            fg = COLORS["muted"]
        _rounded_shape(self, 1, 2, w - 1, h - 1, 7, fill=fill, outline=COLORS["border"], width=1)
        if self._selected:
            self.create_line(10, h - 3, w - 10, h - 3, fill=COLORS["green"], width=3)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)


class SoftNotebook(tk.Frame):
    """Small notebook replacement so tabs can be soft without Qt/third parties."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=COLORS["bg"], bd=0, highlightthickness=0)
        self._tabbar = tk.Frame(self, bg=COLORS["bg"], bd=0, highlightthickness=0)
        self._tabbar.pack(fill="x", pady=(0, 2))
        self._pages: list[tk.Widget] = []
        self._tabs: list[SoftTab] = []
        self._current = -1

    def add(self, child: tk.Widget, *, text: str = "") -> None:
        index = len(self._pages)
        self._pages.append(child)
        tab = SoftTab(self._tabbar, text, lambda i=index: self.select(i))
        tab.pack(side="left", padx=(0, 5))
        self._tabs.append(tab)
        if index == 0:
            self.select(0)
        else:
            child.pack_forget()

    def select(self, index: int | tk.Widget | None = None) -> Any:
        if index is None:
            return self._pages[self._current] if 0 <= self._current < len(self._pages) else None
        if isinstance(index, tk.Widget):
            try:
                new_index = self._pages.index(index)
            except ValueError:
                return None
        else:
            new_index = int(index)
        if not 0 <= new_index < len(self._pages):
            return None
        if 0 <= self._current < len(self._pages):
            self._pages[self._current].pack_forget()
            self._tabs[self._current].set_selected(False)
        self._current = new_index
        self._tabs[new_index].set_selected(True)
        self._pages[new_index].pack(fill="both", expand=True)
        return self._pages[new_index]


class ModernScrollbar(tk.Canvas):
    """Arrowless rounded scrollbar that disappears when all content fits."""

    def __init__(self, parent: tk.Misc, *, orient: str, command: Callable[..., Any]) -> None:
        self.orient = orient
        self.command = command
        self._first = 0.0
        self._last = 1.0
        self._needed = False
        self._hover = False
        self._drag_offset = 0.0
        self._manager = ""
        self._pack_args: tuple[Any, ...] = ()
        self._pack_kwargs: dict[str, Any] = {}
        self._grid_args: tuple[Any, ...] = ()
        self._grid_kwargs: dict[str, Any] = {}
        size = 12
        kwargs = {"width": size, "height": size, "bg": COLORS["panel"], "highlightthickness": 0, "bd": 0}
        super().__init__(parent, **kwargs)
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)

    def pack(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        self._manager = "pack"
        self._pack_args, self._pack_kwargs = args, kwargs.copy()
        if self._needed:
            return super().pack(*args, **kwargs)
        return None

    def grid(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        self._manager = "grid"
        self._grid_args, self._grid_kwargs = args, kwargs.copy()
        if self._needed:
            return super().grid(*args, **kwargs)
        return None

    def set(self, first: str | float, last: str | float) -> None:
        try:
            self._first, self._last = float(first), float(last)
        except (TypeError, ValueError):
            self._first, self._last = 0.0, 1.0
        needed = self._first > 0.0001 or self._last < 0.9999
        if needed != self._needed:
            self._needed = needed
            self._apply_visibility()
        self._redraw()

    def _apply_visibility(self) -> None:
        if self._needed:
            if self._manager == "grid":
                super().grid(*self._grid_args, **self._grid_kwargs)
            elif self._manager == "pack":
                super().pack(*self._pack_args, **self._pack_kwargs)
        else:
            if self.winfo_manager() == "grid":
                super().grid_remove()
            elif self.winfo_manager() == "pack":
                super().pack_forget()

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._redraw()

    def _geometry(self) -> tuple[float, float, float, float]:
        margin = 2.0
        if self.orient == "vertical":
            track = max(1.0, self.winfo_height() - margin * 2)
            span = max(0.0, min(1.0, self._last - self._first))
            length = max(26.0, track * span)
            length = min(track, length)
            max_pos = max(0.0, track - length)
            ratio = 0.0 if span >= 1 else self._first / max(0.000001, 1.0 - span)
            top = margin + max_pos * max(0.0, min(1.0, ratio))
            return 3.0, top, max(4.0, self.winfo_width() - 3.0), top + length
        track = max(1.0, self.winfo_width() - margin * 2)
        span = max(0.0, min(1.0, self._last - self._first))
        length = max(26.0, track * span)
        length = min(track, length)
        max_pos = max(0.0, track - length)
        ratio = 0.0 if span >= 1 else self._first / max(0.000001, 1.0 - span)
        left = margin + max_pos * max(0.0, min(1.0, ratio))
        return left, 3.0, left + length, max(4.0, self.winfo_height() - 3.0)

    def _redraw(self) -> None:
        self.delete("all")
        self._rd_surface_images = []
        if not self._needed or not self.winfo_exists():
            return
        x1, y1, x2, y2 = self._geometry()
        thumb = _shade_color(COLORS["muted"], 1.16 if self._hover and IS_DARK else (0.90 if self._hover else 0.75))
        radius = min(5.0, (x2 - x1) / 2, (y2 - y1) / 2)
        _rounded_shape(self, x1, y1, x2, y2, radius, fill=thumb, outline="")

    def _press(self, event: tk.Event) -> None:
        x1, y1, x2, y2 = self._geometry()
        pos = float(event.y if self.orient == "vertical" else event.x)
        start = y1 if self.orient == "vertical" else x1
        end = y2 if self.orient == "vertical" else x2
        if start <= pos <= end:
            self._drag_offset = pos - start
        else:
            self._drag_offset = (end - start) / 2
            self._moveto_pointer(pos)

    def _drag(self, event: tk.Event) -> None:
        pos = float(event.y if self.orient == "vertical" else event.x)
        self._moveto_pointer(pos)

    def _moveto_pointer(self, pos: float) -> None:
        margin = 2.0
        length_px = self.winfo_height() if self.orient == "vertical" else self.winfo_width()
        track = max(1.0, length_px - margin * 2)
        x1, y1, x2, y2 = self._geometry()
        thumb_len = (y2 - y1) if self.orient == "vertical" else (x2 - x1)
        max_pos = max(1.0, track - thumb_len)
        top = pos - self._drag_offset - margin
        ratio = max(0.0, min(1.0, top / max_pos))
        span = max(0.0, min(1.0, self._last - self._first))
        fraction = ratio * max(0.0, 1.0 - span)
        self.command("moveto", fraction)


def rd_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    kind: str = "primary",
    state: str = "normal",
    icon: str | None = None,
) -> RoundedButton:
    return RoundedButton(parent, text, command, kind=kind, state=state, icon=icon)

def format_timestamp(value: Any, language: str = "en") -> str:
    """Convert Real-Debrid ISO-8601 UTC timestamps to the PC's local timezone."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        normalized = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        month = month_abbr(language, local.month)
        return f"{local.day:02d} {month} {local.year:04d} · {local:%H:%M:%S}"
    except (TypeError, ValueError, OverflowError):
        return raw


def parse_magnet_lines(text: str) -> tuple[list[str], list[str]]:
    """Return unique magnet links and invalid non-empty lines, preserving order."""
    magnets: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.lower().startswith("magnet:?"):
            invalid.append(line)
            continue
        if line not in seen:
            seen.add(line)
            magnets.append(line)
    return magnets, invalid



def _timestamp_sort_key(value: Any) -> float | None:
    """Return an epoch sort key for Real-Debrid ISO timestamps."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _numeric_sort_key(value: Any) -> float | None:
    """Best-effort numeric key used by sortable Treeview columns."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def human_bytes(value: int | float | None) -> str:
    try:
        n = float(value or 0)
    except Exception:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if abs(n) < 1024 or unit == units[-1]:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "download.bin"


def make_flag_icon(master: tk.Misc, flag_code: str, width: int = 24, height: int = 16) -> tk.PhotoImage:
    """Create tiny dependency-free flag icons for the language picker."""
    image = tk.PhotoImage(master=master, width=width, height=height)

    def rect(color: str, x1: int, y1: int, x2: int, y2: int) -> None:
        image.put(color, to=(x1, y1, x2, y2))

    # Thin dark edge makes pale flags readable against the banner.
    rect("#34383C", 0, 0, width, height)
    x0, y0, x1, y1 = 1, 1, width - 1, height - 1
    w, h = x1 - x0, y1 - y0

    if flag_code == "fr":
        third = w // 3
        rect("#0055A4", x0, y0, x0 + third, y1)
        rect("#FFFFFF", x0 + third, y0, x0 + 2 * third, y1)
        rect("#EF4135", x0 + 2 * third, y0, x1, y1)
    elif flag_code == "de":
        third = h // 3
        rect("#111111", x0, y0, x1, y0 + third)
        rect("#DD0000", x0, y0 + third, x1, y0 + 2 * third)
        rect("#FFCE00", x0, y0 + 2 * third, x1, y1)
    elif flag_code == "it":
        third = w // 3
        rect("#009246", x0, y0, x0 + third, y1)
        rect("#FFFFFF", x0 + third, y0, x0 + 2 * third, y1)
        rect("#CE2B37", x0 + 2 * third, y0, x1, y1)
    elif flag_code == "tr":
        rect("#E30A17", x0, y0, x1, y1)
        # Tiny crescent made from two overlapping pixel circles.
        cx, cy, radius = 9, 8, 5
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2:
                    image.put("#FFFFFF", (xx, yy))
        cx2, cy2, r2 = 11, 7, 4
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                if (xx - cx2) ** 2 + (yy - cy2) ** 2 <= r2 ** 2:
                    image.put("#E30A17", (xx, yy))
        for xx, yy in ((16, 8), (17, 6), (18, 8), (17, 10), (19, 8)):
            if 0 <= xx < width and 0 <= yy < height:
                image.put("#FFFFFF", (xx, yy))
    else:  # gb / English
        rect("#21468B", x0, y0, x1, y1)
        # White/red diagonals, then the central cross.
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                relx = xx - x0
                rely = yy - y0
                if abs(relx * h - rely * w) < w * 1.25 or abs(relx * h - (h - 1 - rely) * w) < w * 1.25:
                    image.put("#FFFFFF", (xx, yy))
        rect("#FFFFFF", x0, 6, x1, 10)
        rect("#FFFFFF", 9, y0, 15, y1)
        rect("#CF142B", x0, 7, x1, 9)
        rect("#CF142B", 11, y0, 13, y1)
    return image


class LoginDialog(tk.Toplevel):
    """Real-Debrid open-source device authorization.

    The first authorization asks Real-Debrid for account-bound OAuth client
    credentials. Credentials and refresh tokens are stored through the
    operating system's protected credential backend so future builds can reuse
    the same authorization without putting secrets beside the application.
    """

    def __init__(self, app: "AppController") -> None:
        super().__init__(app.root)
        self.app = app
        self.api = app.api
        self.t = app.t
        self.result = False
        self.oauth_cancel = threading.Event()
        self.oauth_url = ""
        self.title(self.t("auth_title"))
        self.geometry(f"{theme.px(650)}x{theme.px(450)}")
        self.minsize(theme.px(620), theme.px(450))
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.configure(bg=COLORS["bg"])
        apply_windows_titlebar(self)

        frame = ttk.Frame(self, padding=theme.px(18))
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=self.t("auth_heading"), font=theme.font(14, True)).pack(anchor="w")
        ttk.Label(
            frame,
            text=self.t("auth_intro"),
            wraplength=theme.px(590),
        ).pack(anchor="w", pady=(8, 8))

        saved = bool(self.api.store.get("client_id") and self.api.store.get("client_secret") and self.api.store.get("refresh_token"))
        if saved:
            initial = self.t("auth_saved")
            button_text = self.t("replace_auth")
        else:
            initial = self.t("auth_first")
            button_text = self.t("authorize_pc")

        self.oauth_status = tk.StringVar(value=initial)
        ttk.Label(frame, textvariable=self.oauth_status, wraplength=theme.px(590)).pack(anchor="w", pady=(8, 8))

        ttk.Label(frame, text=self.t("device_code")).pack(anchor="w", pady=(5, 0))
        self.oauth_code = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.oauth_code, font=theme.font(18, True)).pack(anchor="w", pady=(0, 8))

        row = FlowRow(frame)
        row.pack(fill="x", pady=6)
        self.oauth_start_btn = rd_button(row, button_text, self._start_oauth, kind="primary")
        row.add(self.oauth_start_btn)
        self.open_btn = rd_button(row, self.t("open_auth_page"), self._open_oauth, kind="secondary", state="disabled")
        row.add(self.open_btn)
        self.copy_btn = rd_button(row, self.t("copy_code"), self._copy_oauth_code, kind="neutral", state="disabled")
        row.add(self.copy_btn)

        ttk.Separator(frame).pack(fill="x", pady=(14, 10))
        ttk.Label(
            frame,
            text=self.t("auth_storage"),
            wraplength=theme.px(590),
        ).pack(anchor="w")

        self.close_btn=rd_button(frame, self.t("close"), self._close, kind="neutral")
        self.close_btn.pack(anchor="e", pady=(14, 0))
        self.update_idletasks()
        height=max(theme.px(450),frame.winfo_reqheight()+theme.px(8))
        self.geometry(f"{theme.px(650)}x{height}")
        self.minsize(theme.px(620),height)
        self.grab_set()
        self.focus_force()

    def _start_oauth(self) -> None:
        already_saved = bool(
            self.api.store.get("client_id")
            and self.api.store.get("client_secret")
            and self.api.store.get("refresh_token")
        )
        if already_saved:
            proceed = messagebox.askyesno(
                self.t("replace_auth_title"),
                self.t("replace_auth_warning"),
                parent=self,
            )
            if not proceed:
                return

        self.oauth_cancel.clear()
        self.oauth_start_btn.configure(state="disabled")
        self.oauth_status.set(self.t("requesting_device_code"))

        def started(payload: dict[str, Any]) -> None:
            self.oauth_url = str(payload.get("verification_url", ""))
            code = str(payload.get("user_code", ""))
            self.oauth_code.set(code)
            self.oauth_status.set(self.t("auth_enter_code"))
            self.open_btn.configure(state="normal" if self.oauth_url else "disabled")
            self.copy_btn.configure(state="normal" if code else "disabled")
            self._poll_oauth(payload)

        self.app.async_call(self.api.start_open_source_oauth, started, self._oauth_failed, parent=self)

    def _poll_oauth(self, payload: dict[str, Any]) -> None:
        device_code = str(payload.get("device_code", ""))
        interval = max(2, int(payload.get("interval", 5) or 5))
        expires = max(30, int(payload.get("expires_in", 1800) or 1800))

        def job() -> dict[str, Any]:
            deadline = time.time() + expires
            while time.time() < deadline and not self.oauth_cancel.is_set():
                creds = self.api.poll_open_source_credentials(device_code)
                if creds:
                    tokens = self.api.exchange_device_code(creds["client_id"], creds["client_secret"], device_code)
                    return {"creds": creds, "tokens": tokens}
                time.sleep(interval)
            raise RealDebridError(self.t("auth_cancelled_expired"))

        def ok(result: dict[str, Any]) -> None:
            creds = result["creds"]
            tokens = result["tokens"]
            try:
                self.api.store.save_oauth(
                    client_id=creds["client_id"],
                    client_secret=creds["client_secret"],
                    access_token=tokens["access_token"],
                    refresh_token=tokens["refresh_token"],
                    expires_in=int(tokens.get("expires_in", 0)),
                    persistent=True,
                )
            except Exception as exc:
                logging.exception("OAuth credentials were issued but could not be stored securely")
                self._oauth_failed(str(exc) or exc.__class__.__name__)
                return
            self.app.async_call(self.api.test_auth, self._success, self._oauth_failed, parent=self)

        self.app.async_call(job, ok, self._oauth_failed, parent=self)

    def _oauth_failed(self, message: str) -> None:
        self.oauth_start_btn.configure(state="normal")
        self.oauth_status.set(message)

    def _open_oauth(self) -> None:
        if self.oauth_url:
            webbrowser.open(self.oauth_url)

    def _copy_oauth_code(self) -> None:
        value = self.oauth_code.get().strip()
        if value:
            self.clipboard_clear()
            self.clipboard_append(value)

    def _success(self, user: dict[str, Any]) -> None:
        self.result = True
        self.oauth_cancel.set()
        self.grab_release()
        self.destroy()
        self.app.set_status(self.t("signed_in_saved", username=user.get("username", "")))
        self.app.refresh_all()

    def _close(self) -> None:
        self.oauth_cancel.set()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class FileSelectionDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, info: dict[str, Any], language: str = "en") -> None:
        super().__init__(parent)
        self.language = normalize_language(language)
        self.t = lambda key, **kwargs: tr(self.language, key, **kwargs)
        self.title(self.t("choose_torrent_files_title"))
        self.geometry(f"{theme.px(780)}x{theme.px(500)}")
        self.result: list[int] | None = None
        self.transient(parent)
        self.grab_set()
        self.configure(bg=COLORS["bg"])
        apply_windows_titlebar(self)

        ttk.Label(self, text=str(info.get("filename", "Torrent")), font=theme.font(11, True)).pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        panel = RoundedPanel(self)
        panel.pack(fill="both", expand=True, padx=10, pady=6)
        frame = panel.inner
        self.tree = ttk.Treeview(frame, columns=("id", "path", "size"), show="headings", selectmode="extended")
        self.tree.heading("id", text=self.t("col_id"), anchor="e")
        self.tree.heading("path", text=self.t("col_path"), anchor="w")
        self.tree.heading("size", text=self.t("col_size"), anchor="e")
        self.tree.column("id", width=70, anchor="e")
        self.tree.column("path", width=520)
        self.tree.column("size", width=120, anchor="e")
        y = ModernScrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        initially_selected: list[str] = []
        for f in info.get("files", []):
            fid = str(f.get("id"))
            self.tree.insert("", "end", iid=fid, values=(fid, f.get("path", ""), human_bytes(f.get("bytes", 0))))
            if f.get("selected"):
                initially_selected.append(fid)
        if initially_selected:
            self.tree.selection_set(initially_selected)

        row = ttk.Frame(self)
        row.pack(fill="x", padx=10, pady=(0, 10))
        rd_button(row, self.t("select_all"), lambda: self.tree.selection_set(self.tree.get_children()), kind="secondary").pack(side="left")
        rd_button(row, self.t("select_none"), lambda: self.tree.selection_remove(self.tree.get_children()), kind="neutral").pack(side="left", padx=6)
        rd_button(row, self.t("cancel"), self._cancel, kind="neutral").pack(side="right")
        rd_button(row, self.t("use_selected_files"), self._ok, kind="primary").pack(side="right", padx=6)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _ok(self) -> None:
        selected = [int(x) for x in self.tree.selection()]
        if not selected:
            messagebox.showwarning(self.t("torrent_files_title"), self.t("select_at_least_one"), parent=self)
            return
        self.result = selected
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()


class MagnetBatchDialog(tk.Toplevel):
    """Multi-line magnet entry dialog used by the sequential add queue."""

    def __init__(self, parent: tk.Misc, language: str = "en") -> None:
        super().__init__(parent)
        self.language = normalize_language(language)
        self.result: list[str] | None = None
        self.title(self.t("add_magnets_title"))
        self.geometry(f"{theme.px(720)}x{theme.px(390)}")
        self.minsize(theme.px(560), theme.px(320))
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        apply_windows_titlebar(self)

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=self.t("paste_magnets"), font=theme.font(10, True)).pack(anchor="w")
        self.text = style_text_widget(tk.Text(outer, height=11, wrap="word"))
        self.text.pack(fill="both", expand=True, pady=(7, 8))
        ttk.Label(outer, text=self.t("batch_upload_note"), foreground=COLORS["muted"], wraplength=650).pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(outer)
        row.pack(fill="x")
        rd_button(row, self.t("cancel"), self._cancel, kind="neutral").pack(side="right")
        rd_button(row, self.t("queue_magnets"), self._ok, kind="primary").pack(side="right", padx=(0, 7))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(50, lambda: self.text.focus_set())
        self.grab_set()

    def t(self, key: str, **kwargs: Any) -> str:
        return tr(self.language, key, **kwargs)

    def _ok(self) -> None:
        magnets, invalid = parse_magnet_lines(self.text.get("1.0", "end"))
        if invalid:
            preview = "\n".join(invalid[:4])
            if len(invalid) > 4:
                preview += f"\n… (+{len(invalid) - 4})"
            messagebox.showwarning(
                self.t("add_magnets_title"),
                self.t("invalid_magnets", count=len(invalid), details=preview),
                parent=self,
            )
            return
        if not magnets:
            messagebox.showinfo(self.t("add_magnets_title"), self.t("no_magnets"), parent=self)
            return
        self.result = magnets
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class UploadQueueWindow(tk.Toplevel):
    """Non-modal progress window for sequential torrent/magnet additions."""

    def __init__(self, parent: tk.Misc, items: list[dict[str, str]], language: str = "en") -> None:
        super().__init__(parent)
        self.language = normalize_language(language)
        self.running = True
        self.title(self.t("upload_queue_title"))
        self.geometry(f"{theme.px(820)}x{theme.px(420)}")
        self.minsize(theme.px(660), theme.px(330))
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        apply_windows_titlebar(self)

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=self.t("upload_queue_title"), font=theme.font(11, True)).pack(anchor="w", pady=(0, 4))
        ttk.Label(outer, text=self.t("batch_upload_note"), foreground=COLORS["muted"], wraplength=760).pack(anchor="w", pady=(0, 9))

        panel = RoundedPanel(outer)
        panel.pack(fill="both", expand=True)
        frame = panel.inner
        self.tree = ttk.Treeview(frame, columns=("type", "item", "status"), show="headings", selectmode="none")
        self.tree.heading("type", text=self.t("col_type"), anchor="w")
        self.tree.heading("item", text=self.t("col_item"), anchor="w")
        self.tree.heading("status", text=self.t("col_status"), anchor="w")
        self.tree.column("type", width=95, anchor="w", stretch=False)
        self.tree.column("item", width=470, anchor="w", stretch=True)
        self.tree.column("status", width=200, anchor="w", stretch=False)
        self.tree.tag_configure("queued", foreground=COLORS["muted"])
        self.tree.tag_configure("active", foreground=COLORS["blue"])
        self.tree.tag_configure("done", foreground=COLORS["green"])
        self.tree.tag_configure("skipped", foreground=COLORS["muted"])
        self.tree.tag_configure("error", foreground=COLORS["red"])
        y = ModernScrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        for index, item in enumerate(items):
            kind = self.t("queue_torrent") if item["kind"] == "torrent" else self.t("queue_magnet")
            self.tree.insert("", "end", iid=str(index), values=(kind, item["label"], self.t("queue_queued")), tags=("queued",))

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        self.summary_var = tk.StringVar(value=self.t("upload_queue_waiting", count=len(items)))
        ttk.Label(bottom, textvariable=self.summary_var, foreground=COLORS["muted"]).pack(side="left", fill="x", expand=True)
        self.close_btn = rd_button(bottom, self.t("hide"), self._close_or_hide, kind="neutral")
        self.close_btn.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._close_or_hide)

    def t(self, key: str, **kwargs: Any) -> str:
        return tr(self.language, key, **kwargs)

    def show(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def set_item(self, index: int, status: str, tag: str = "active") -> None:
        if not self.winfo_exists() or not self.tree.exists(str(index)):
            return
        values = list(self.tree.item(str(index), "values"))
        while len(values) < 3:
            values.append("")
        values[2] = status
        self.tree.item(str(index), values=values, tags=(tag,))
        self.tree.see(str(index))

    def set_progress(self, index: int, total: int) -> None:
        if self.winfo_exists():
            self.summary_var.set(self.t("upload_queue_running", index=index, total=total))

    def finish(self, added: int, failed: int, skipped: int = 0) -> None:
        if not self.winfo_exists():
            return
        self.running = False
        self.summary_var.set(self.t("upload_queue_complete", added=added, skipped=skipped, failed=failed))
        self.close_btn.configure(text=self.t("close"))
        self.show()

    def _close_or_hide(self) -> None:
        if self.running:
            self.withdraw()
        else:
            self.destroy()

class AppController:
    """Shared controller logic. The visual shell lives entirely in RDModernApp."""
    def t(self, key: str, **kwargs: Any) -> str:
        return tr(self.language, key, **kwargs)
    def _torrent_status_text(self, raw: str) -> str:
        key = f"torrent_status_{raw}"
        translated = self.t(key)
        if translated != key:
            return translated
        return raw.replace("_", " ").strip().title()
    def post(self, fn: Callable[..., Any], *args: Any) -> None:
        self.ui_queue.put((fn, args))
    def _drain_ui_queue(self) -> None:
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception as exc:
                    self._tk_exception(type(exc), exc, exc.__traceback__)
        except queue.Empty:
            pass
        self.root.after(50, self._drain_ui_queue)
    def async_call(
        self,
        fn: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        *,
        busy: str | None = None,
        parent: tk.Misc | None = None,
    ) -> None:
        if busy:
            self.set_status(busy)

        def worker() -> None:
            try:
                result = fn()
            except Exception as exc:
                msg = str(exc) or exc.__class__.__name__
                self.post(on_error or (lambda m: messagebox.showerror("Real-Debrid", m, parent=parent or self.root)), msg)
            else:
                if on_success:
                    self.post(on_success, result)
            finally:
                if busy:
                    self.post(self.set_status, self.t("ready"))

        threading.Thread(target=worker, daemon=True).start()
    def _tk_exception(self, exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        import logging
        logging.exception("Tk callback exception", exc_info=(exc_type, exc, tb))
        messagebox.showerror("RD Desktop", self.t("unexpected_error", error=exc), parent=self.root)
    def _configure_theme(self) -> None:
        theme.configure_theme(self.root)
    def _build_language_selector(self, parent: tk.Misc) -> None:
        labels = {"en": "English", "fr": "Français", "tr": "Türkçe", "de": "Deutsch", "it": "Italiano"}
        style = ttk.Style(self.root)
        style.configure("Language.TMenubutton", background=COLORS["panel"], foreground=COLORS["text"],
                        bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"],
                        arrowcolor=COLORS["muted"], relief="flat", padding=(theme.px(5), theme.px(3)), font=theme.font(9))
        style.map("Language.TMenubutton", background=[("active", COLORS["neutral_hover"])])
        button = ttk.Menubutton(parent, text=labels[normalize_language(self.language)], style="Language.TMenubutton", cursor="hand2", takefocus=True)
        menu = tk.Menu(button, tearoff=False, bg=COLORS["panel"], fg=COLORS["text"],
                       activebackground=COLORS["selection"], activeforeground=COLORS["text"], bd=0, font=theme.font(10))
        for code, _label, _flag in LANGUAGE_OPTIONS:
            menu.add_command(label=labels[code], command=lambda c=code: self._change_language(c))
        button.configure(menu=menu)
        button.pack(anchor="e")
        self.flag_images = {}
        self.language_button, self.language_menu = button, menu
    def set_status(self, text: str) -> None:
        self.status_var.set(text)
    def ensure_login(self) -> None:
        if not self.api.authenticated:
            self.open_login()
            return

        # Validate/reuse the saved authorization. A temporary network/API error
        # must never generate a new Real-Debrid device credential automatically.
        def ok(user: dict[str, Any]) -> None:
            self.set_status(self.t("signed_in_reuse", username=user.get("username", "")))
            self.refresh_all()

        def fail(message: str) -> None:
            self.set_status(self.t("saved_auth_invalid"))
            messagebox.showerror(
                self.t("saved_auth_error_title"),
                self.t("saved_auth_error", message=message),
                parent=self.root,
            )

        self.async_call(self.api.test_auth, ok, fail, parent=self.root)
    def open_login(self) -> None:
        LoginDialog(self)
    def logout(self) -> None:
        if messagebox.askyesno(
            self.t("forget_auth_title"),
            self.t("forget_auth_warning"),
            parent=self.root,
        ):
            self.store.clear_auth()
            self.set_status(self.t("local_auth_removed"))
            self.open_login()
    def refresh_all(self) -> None:
        self.refresh_torrents()
        self.refresh_history()
        self.refresh_account()
    def _auto_refresh(self) -> None:
        if self.api.authenticated and not self.delete_in_progress and not self.upload_in_progress:
            self.refresh_torrents(silent=True)
        self.root.after(5000, self._auto_refresh)
    def refresh_history(self) -> None:
        if not self.api.authenticated or self.history_refreshing:
            return
        self.history_refreshing = True

        def done(rows: list[dict[str, Any]]) -> None:
            self.history_refreshing = False
            self.history_data = {}
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
            for d in rows:
                did = str(d.get("id", ""))
                if not did:
                    continue
                self.history_data[did] = d
                self.history_tree.insert(
                    "",
                    "end",
                    iid=did,
                    values=(
                        d.get("filename", ""),
                        d.get("host", ""),
                        human_bytes(d.get("filesize", 0)),
                        format_timestamp(d.get("generated", ""), self.language),
                        d.get("download", ""),
                    ),
                )
            reapply = getattr(self, "_reapply_tree_sort", None)
            if callable(reapply):
                reapply(self.history_tree)

        def fail(msg: str) -> None:
            self.history_refreshing = False
            messagebox.showerror("Real-Debrid", msg)

        self.async_call(self.api.downloads, done, fail, busy=self.t("refreshing_history"))
    def _selected_torrent_ids(self) -> list[str]:
        return list(self.torrent_tree.selection())
    def _one_torrent(self) -> str | None:
        selected = self._selected_torrent_ids()
        if len(selected) != 1:
            messagebox.showinfo(self.t("select_torrent_title"), self.t("select_exactly_one"))
            return None
        return selected[0]
    def _queue_item_label(self, value: str, kind: str) -> str:
        if kind == "torrent":
            return Path(value).name
        compact = value.strip()
        return compact if len(compact) <= 92 else compact[:89] + "…"
    def _existing_torrent_hashes(self) -> dict[str, dict[str, Any]]:
        """Return Real-Debrid torrents indexed by canonical BTIH info hash."""
        existing: dict[str, dict[str, Any]] = {}
        for torrent in self.api.torrents():
            info_hash = normalize_info_hash(torrent.get("hash"))
            if info_hash:
                existing[info_hash] = torrent
        return existing
    def _add_single_item_checked(self, kind: str, value: str) -> dict[str, Any]:
        """Add one torrent/magnet, skipping it before upload when it already exists."""
        info_hash = item_info_hash(kind, value)
        if info_hash:
            existing = self._existing_torrent_hashes().get(info_hash)
            if existing is not None:
                return {"skipped": True, "existing": existing, "info_hash": info_hash}

        created = self.api.add_torrent(value) if kind == "torrent" else self.api.add_magnet(value)
        tid = str(created.get("id", "") or "")
        if not tid:
            raise RealDebridError(self.t("torrent_no_id"))
        return {
            "skipped": False,
            "tid": tid,
            "info": self._wait_for_files(tid),
            "info_hash": info_hash,
        }
    def _after_single_item_checked(self, result: dict[str, Any]) -> None:
        if result.get("skipped"):
            existing = result.get("existing") or {}
            name = str(existing.get("filename") or self.t("torrent_existing_item"))
            messagebox.showinfo(
                self.t("torrent_exists_title"),
                self.t("torrent_exists_skipped", name=name),
                parent=self.root,
            )
            tid = str(existing.get("id") or "")
            if tid and self.torrent_tree.exists(tid):
                self.torrent_tree.selection_set(tid)
                self.torrent_tree.see(tid)
            self.refresh_torrents(silent=True)
            return
        self._after_torrent_added((str(result["tid"]), result.get("info") or {}))
    def _show_existing_upload_queue(self) -> bool:
        if not self.upload_in_progress:
            return False
        if self.upload_queue_window is not None:
            try:
                self.upload_queue_window.show()
            except tk.TclError:
                pass
        self.set_status(self.t("upload_queue_already_running"))
        return True
    def _start_upload_queue(self, items: list[dict[str, str]]) -> None:
        if not items or self._show_existing_upload_queue():
            return
        self.upload_in_progress = True
        try:
            self.upload_torrent_btn.configure(state="disabled")
            self.add_magnet_btn.configure(state="disabled")
        except Exception:
            pass
        queue_window = UploadQueueWindow(self.root, items, self.language)
        self.upload_queue_window = queue_window
        total = len(items)
        self.set_status(self.t("upload_queue_waiting", count=total))

        def job() -> dict[str, Any]:
            added: list[tuple[str, str]] = []
            skipped: list[str] = []
            failed: list[tuple[str, str]] = []
            existing_hashes = self._existing_torrent_hashes()
            for zero_index, item in enumerate(items):
                index = zero_index + 1
                kind = item["kind"]
                value = item["value"]
                self.post(queue_window.set_progress, index, total)
                info_hash = item_info_hash(kind, value)
                if info_hash and info_hash in existing_hashes:
                    skipped.append(item["label"])
                    self.post(queue_window.set_item, zero_index, self.t("queue_skipped_existing"), "skipped")
                    continue
                active_text = self.t("queue_uploading") if kind == "torrent" else self.t("queue_adding")
                self.post(queue_window.set_item, zero_index, active_text, "active")
                try:
                    def add_once() -> dict[str, Any]:
                        return self.api.add_torrent(value) if kind == "torrent" else self.api.add_magnet(value)

                    try:
                        created = add_once()
                    except RealDebridError as exc:
                        # Respect Real-Debrid rate limiting without turning the whole batch into a failure.
                        if exc.status == 429 or exc.error_code == 34:
                            time.sleep(4.0)
                            created = add_once()
                        else:
                            raise
                    tid = str(created.get("id", ""))
                    if not tid:
                        raise RealDebridError(self.t("torrent_no_id"))

                    final_text = self.t("queue_added_choose_files")
                    if self.store.public.auto_select_all:
                        self.post(queue_window.set_item, zero_index, self.t("queue_waiting_files"), "active")
                        info = self._wait_for_files(tid, timeout=30 if kind == "torrent" else 60)
                        if info.get("files"):
                            self.post(queue_window.set_item, zero_index, self.t("queue_selecting_all"), "active")
                            self._select_files_resilient(tid, "all")
                            final_text = self.t("queue_added_selected")
                        else:
                            final_text = self.t("queue_added_choose_files")
                    self.post(queue_window.set_item, zero_index, final_text, "done")
                    added.append((tid, item["label"]))
                    if info_hash:
                        # Prevent duplicate work for the same torrent repeated
                        # later in this very batch, without another API call.
                        existing_hashes[info_hash] = {"id": tid, "hash": info_hash}
                except Exception as exc:
                    message = str(exc) or exc.__class__.__name__
                    failed.append((item["label"], message))
                    self.post(queue_window.set_item, zero_index, self.t("queue_failed", error=message), "error")
                if index < total:
                    time.sleep(1.25)
            return {"added": added, "skipped": skipped, "failed": failed}

        def done(result: dict[str, Any]) -> None:
            self.upload_in_progress = False
            try:
                self.upload_torrent_btn.configure(state="normal")
                self.add_magnet_btn.configure(state="normal")
            except Exception:
                pass
            added = len(result.get("added", []))
            skipped = len(result.get("skipped", []))
            failed = len(result.get("failed", []))
            queue_window.finish(added, failed, skipped)
            self.set_status(self.t("upload_queue_complete", added=added, skipped=skipped, failed=failed))
            self.refresh_torrents(silent=True)

        def fail(msg: str) -> None:
            self.upload_in_progress = False
            try:
                self.upload_torrent_btn.configure(state="normal")
                self.add_magnet_btn.configure(state="normal")
            except Exception:
                pass
            queue_window.finish(0, total, 0)
            messagebox.showerror(self.t("upload_queue_title"), msg, parent=self.root)

        self.async_call(job, done, fail)
    def add_magnet(self) -> None:
        if self._show_existing_upload_queue():
            return
        dlg = MagnetBatchDialog(self.root, self.language)
        self.root.wait_window(dlg)
        magnets = dlg.result or []
        if not magnets:
            return

        # A single magnet keeps the existing interactive file-selection flow.
        if len(magnets) == 1:
            magnet = magnets[0]
            self.async_call(
                lambda: self._add_single_item_checked("magnet", magnet),
                self._after_single_item_checked,
                busy=self.t("adding_magnet"),
            )
            return

        items = [
            {"kind": "magnet", "value": magnet, "label": self._queue_item_label(magnet, "magnet")}
            for magnet in magnets
        ]
        self._start_upload_queue(items)
    def _after_torrent_added(self, result: tuple[str, dict[str, Any]]) -> None:
        tid, info = result
        if not info.get("files"):
            messagebox.showinfo(self.t("torrent_added_title"), self.t("torrent_files_not_ready"))
            self.refresh_torrents()
            return
        if self.store.public.auto_select_all:
            self.async_call(lambda: self._select_files_resilient(tid, "all"), lambda _: self.refresh_torrents(), busy=self.t("selecting_files"))
            return
        dlg = FileSelectionDialog(self.root, info, self.language)
        self.root.wait_window(dlg)
        if dlg.result:
            self.async_call(lambda: self._select_files_resilient(tid, dlg.result or []), lambda _: self.refresh_torrents(), busy=self.t("selecting_files"))
    def choose_files(self) -> None:
        tid = self._one_torrent()
        if not tid:
            return

        def done(info: dict[str, Any]) -> None:
            dlg = FileSelectionDialog(self.root, info, self.language)
            self.root.wait_window(dlg)
            if dlg.result:
                self.async_call(lambda: self._select_files_resilient(tid, dlg.result or []), lambda _: self.refresh_torrents(), busy=self.t("selecting_files"))

        self.async_call(lambda: self._wait_for_files(tid), done, busy=self.t("loading_torrent_files"))
    def _unrestrict_torrent_links(self, tid: str) -> list[dict[str, Any]]:
        info = self.api.torrent_info(tid)
        if info.get("status") != "downloaded":
            raise RealDebridError(self.t("torrent_not_ready", status=info.get("status", "unknown")))
        links = list(info.get("links") or [])
        if not links:
            raise RealDebridError(self.t("torrent_no_links"))
        items: list[dict[str, Any]] = []
        for link in links:
            result = self.api.unrestrict_link(str(link))
            if isinstance(result, list):
                items.extend(x for x in result if isinstance(x, dict))
            elif isinstance(result, dict):
                items.append(result)
        return items
    def delete_torrents(self) -> None:
        ids = self._selected_torrent_ids()
        if not ids:
            messagebox.showinfo(self.t("delete_torrents_title"), self.t("select_torrents_first"))
            return
        if not messagebox.askyesno(
            self.t("delete_torrents_title"),
            self.t("delete_torrents_confirm", count=len(ids)),
        ):
            return
        self.delete_in_progress = True
        self.delete_torrent_btn.configure(state="disabled")

        def job() -> dict[str, Any]:
            deleted: list[str] = []
            failed: list[tuple[str, str]] = []
            for index, tid in enumerate(ids, start=1):
                self.post(self.set_status, self.t("deleting_torrent", index=index, total=len(ids)))
                try:
                    self.api.delete_torrent(tid)
                    deleted.append(tid)
                except RealDebridError as exc:
                    if exc.status == 404 or exc.error_code == 7:
                        deleted.append(tid)
                    elif exc.status == 429 or exc.error_code == 34:
                        time.sleep(4.0)
                        try:
                            self.api.delete_torrent(tid)
                            deleted.append(tid)
                        except Exception as retry_exc:
                            failed.append((tid, str(retry_exc)))
                    else:
                        failed.append((tid, str(exc)))
                except Exception as exc:
                    failed.append((tid, str(exc)))
                if index < len(ids):
                    time.sleep(1.25)
            return {"deleted": deleted, "failed": failed}

        def done(result: dict[str, Any]) -> None:
            self.delete_in_progress = False
            self.delete_torrent_btn.configure(state="normal")
            self.refresh_torrents()
            failed = result.get("failed", [])
            if failed:
                messagebox.showwarning(
                    self.t("delete_queue_finished"),
                    self.t("delete_queue_result", deleted=len(result.get("deleted", [])), total=len(ids), details="\n".join(f"{tid}: {msg}" for tid, msg in failed[:10])),
                )
            else:
                self.set_status(self.t("deleted_torrents", count=len(ids)))

        def fail(msg: str) -> None:
            self.delete_in_progress = False
            self.delete_torrent_btn.configure(state="normal")
            messagebox.showerror(self.t("delete_queue"), msg)

        self.async_call(job, done, fail)
    def unrestrict_manual(self) -> None:
        links = [x.strip() for x in self.link_input.get("1.0", "end").splitlines() if x.strip()]
        if not links:
            return
        password = self.link_password.get()
        remote = bool(self.remote_var.get())

        def job() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for link in links:
                result = self.api.unrestrict_link(link, password=password, remote=remote)
                if isinstance(result, list):
                    out.extend(x for x in result if isinstance(x, dict))
                elif isinstance(result, dict):
                    out.append(result)
            return out

        def done(items: list[dict[str, Any]]) -> None:
            self.pending_folder_links = []
            self.last_unrestricted = items
            self.link_result.delete("1.0", "end")
            self.link_result.insert("1.0", json.dumps(items, indent=2))

        self.async_call(job, done, busy=self.t("unrestricting_links"))
    def unrestrict_folder(self) -> None:
        links = [x.strip() for x in self.link_input.get("1.0", "end").splitlines() if x.strip()]
        if len(links) != 1:
            messagebox.showinfo(self.t("folder_link_title"), self.t("enter_one_folder"))
            return

        def done(items: list[str]) -> None:
            self.last_unrestricted = []
            self.pending_folder_links = list(items)
            self.link_result.delete("1.0", "end")
            self.link_result.insert("1.0", "\n".join(items))

        self.async_call(lambda: self.api.unrestrict_folder(links[0]), done, busy=self.t("expanding_folder"))
    def delete_history(self) -> None:
        ids = list(self.history_tree.selection())
        if not ids:
            return
        if not messagebox.askyesno(self.t("delete_history_title"), self.t("delete_history_confirm", count=len(ids))):
            return

        def job() -> dict[str, Any]:
            deleted = 0
            failed: list[str] = []
            for index, did in enumerate(ids):
                try:
                    self.api.delete_download(did)
                    deleted += 1
                except RealDebridError as exc:
                    if exc.status == 404 or exc.error_code == 7:
                        deleted += 1
                    else:
                        failed.append(f"{did}: {exc}")
                if index + 1 < len(ids):
                    time.sleep(1.0)
            return {"deleted": deleted, "failed": failed}

        def done(result: dict[str, Any]) -> None:
            self.refresh_history()
            if result["failed"]:
                messagebox.showwarning(self.t("history_delete_title"), "\n".join(result["failed"][:10]))

        self.async_call(job, done, busy=self.t("deleting_history", count=len(ids)))
    def open_log_folder(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        open_path(CONFIG_DIR)

# ---------------------------------------------------------------------------
# Modern UI download-manager layer
# ---------------------------------------------------------------------------
import logging
import ctypes
from ctypes import wintypes

DOWNLOADS_FILE = data_dir() / "local-downloads.json"


def normalize_download_limit(value: Any, current: int = 3) -> tuple[int, bool]:
    """Return a safe local-download concurrency and whether the input was valid.

    The UI accepts whole numbers only. Out-of-range numbers are clamped to the
    documented application range; malformed/blank input falls back to the last
    valid value.
    """
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return max(1, min(MAX_SAFE_SIMULTANEOUS_DOWNLOADS, int(current))), False
    if parsed < 1:
        return 1, False
    if parsed > MAX_SAFE_SIMULTANEOUS_DOWNLOADS:
        return MAX_SAFE_SIMULTANEOUS_DOWNLOADS, False
    return parsed, True


def download_limit_text_needs_warning(value: Any) -> bool:
    """Return True when non-blank text cannot represent a valid 1..8 limit.

    Blank text is tolerated while the user is in the middle of replacing the
    value. Focus-out/Enter still normalizes blank input via ``commit``.
    """
    text = str(value).strip()
    if not text:
        return False
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        return True
    return parsed < 1 or parsed > MAX_SAFE_SIMULTANEOUS_DOWNLOADS


class NumberStepper(tk.Canvas):
    """Compact modern integer input with stacked up/down chevrons."""

    def __init__(
        self,
        parent: tk.Misc,
        value: int,
        command: Callable[[int], None],
        invalid_command: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            width=theme.px(96),
            height=theme.px(38),
            bg=COLORS["panel"],
            highlightthickness=0,
            bd=0,
            cursor="xterm",
        )
        self.command = command
        self.invalid_command = invalid_command
        self.last_valid = max(1, min(MAX_SAFE_SIMULTANEOUS_DOWNLOADS, int(value)))
        self.var = tk.StringVar(value=str(self.last_valid))
        self.entry = tk.Entry(
            self,
            textvariable=self.var,
            justify="center",
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=COLORS["field"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["blue_button"],
            selectforeground="#FFFFFF",
            font=theme.font(10, True),
        )
        self.create_window(theme.px(35), theme.px(19), width=theme.px(54), height=theme.px(28), window=self.entry)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._click)
        self.entry.bind("<Return>", self._commit_event)
        self.entry.bind("<FocusOut>", self._commit_event)
        self.entry.bind("<FocusIn>", lambda _e: self._draw(), add="+")
        self.entry.bind("<FocusOut>", lambda _e: self._draw(), add="+")
        self.entry.bind("<Up>", lambda _e: self._step(1))
        self.entry.bind("<Down>", lambda _e: self._step(-1))
        # Live validation: warn as soon as typed text becomes invalid/out of
        # range instead of waiting for Enter or focus loss. Blank is allowed
        # transiently while replacing the value and is normalized on commit.
        self._var_trace = self.var.trace_add("write", self._on_var_write)
        self._draw()

    def _on_var_write(self, *_args: Any) -> None:
        if download_limit_text_needs_warning(self.var.get()):
            self.invalid_command()

    def _draw(self) -> None:
        self.delete("chrome")
        self._rd_surface_images = []
        w=max(theme.px(96),self.winfo_width()); h=max(theme.px(38),self.winfo_height())
        _rounded_shape(self, 0, 0, w, h, theme.px(7), fill=COLORS["field"], outline=COLORS["blue"] if self.focus_get()==self.entry else COLORS["border"], tags="chrome")
        x=w-theme.px(30)
        self.create_line(x, theme.px(6), x, h-theme.px(6), fill=COLORS["border"], tags="chrome")
        self.create_line(x, h/2, w-theme.px(4), h/2, fill=COLORS["border"], tags="chrome")
        cx=(x+w-theme.px(4))/2
        _draw_icon(self,"chevron_up",cx,h/4+theme.px(1),COLORS["muted"],scale=theme.px(14)/24,tag="chrome")
        _draw_icon(self,"chevron_down",cx,h*3/4-theme.px(1),COLORS["muted"],scale=theme.px(14)/24,tag="chrome")
        self.tag_lower("chrome")

    def _click(self, event: tk.Event) -> str | None:
        if event.x >= max(theme.px(66), self.winfo_width()-theme.px(30)):
            self._step(1 if event.y < self.winfo_height()/2 else -1)
            return "break"
        self.entry.focus_set()
        return None

    def _step(self, delta: int) -> str:
        value, valid = normalize_download_limit(self.var.get(), self.last_valid)
        if not valid:
            # First recover an invalid typed value to the nearest safe value; a
            # second click can then step normally. This avoids 9 + down jumping
            # unexpectedly to 7, or 0 + up jumping to 2.
            self.invalid_command()
            self._apply(value)
            return "break"
        proposed=value+delta
        if proposed < 1 or proposed > MAX_SAFE_SIMULTANEOUS_DOWNLOADS:
            self.invalid_command()
            proposed=max(1,min(MAX_SAFE_SIMULTANEOUS_DOWNLOADS,proposed))
        self._apply(proposed)
        return "break"

    def _commit_event(self, _event: tk.Event | None = None) -> str:
        self.commit()
        return "break"

    def commit(self) -> int:
        value, valid = normalize_download_limit(self.var.get(), self.last_valid)
        if not valid:
            self.invalid_command()
        self._apply(value)
        return value

    def _apply(self, value: int) -> None:
        value=max(1,min(MAX_SAFE_SIMULTANEOUS_DOWNLOADS,int(value)))
        changed=value != self.last_valid
        self.last_valid=value
        self.var.set(str(value))
        if changed:
            self.command(value)




class SidebarBook(tk.Frame):
    def __init__(self, parent: tk.Misc, nav_parent: tk.Misc) -> None:
        super().__init__(parent, bg=COLORS["bg"], bd=0, highlightthickness=0)
        self.nav_parent=nav_parent; self.pages=[]; self.buttons=[]; self._current=0
        self.icons=["link","torrent","download","history","user","settings"]
    def add(self, frame: tk.Widget, text: str) -> None:
        idx=len(self.pages); self.pages.append(frame)
        b=SidebarNavButton(self.nav_parent,text,self.icons[idx] if idx<len(self.icons) else "•",lambda i=idx:self.select(i))
        b.pack(fill="x", pady=2)
        self.buttons.append(b)
        if idx==0: self.select(0)
    def select(self, index: int) -> None:
        if not self.pages: return
        index=max(0,min(index,len(self.pages)-1)); self._current=index
        for i,p in enumerate(self.pages):
            if i==index: p.pack(fill="both",expand=True)
            else: p.pack_forget()
            self.buttons[i].set_selected(i==index)


class RubberBandSelector:
    """Explorer-like mouse selection for visible Treeview rows.

    Tk's native extended-selection anchor can be established a click later than
    the visual selection when a widget-level mouse binding is also installed.
    Keep an explicit anchor so the *first* Shift-click always selects the whole
    range, consistently on Windows and Linux.
    """
    SHIFT_MASK = 0x0001
    CTRL_MASK = 0x0004

    def __init__(self, tree: ttk.Treeview) -> None:
        self.tree=tree; self.start_x=0; self.start_y=0; self.dragging=False; self.base=(); self.ctrl=False; self.anchor=None; self.overlay=None
        tree.bind("<ButtonPress-1>",self.press,add="+")
        tree.bind("<B1-Motion>",self.motion,add="+")
        tree.bind("<ButtonRelease-1>",self.release,add="+")
        tree.bind("<Control-a>",self.select_all,add="+")
    def select_all(self,_e=None):
        self.tree.selection_set(self.tree.get_children()); return "break"
    def _select_range(self, row: str, *, additive: bool) -> str | None:
        children=list(self.tree.get_children())
        if row not in children:
            return None
        anchor=self.anchor
        if anchor not in children:
            focused=self.tree.focus()
            if focused in children:
                anchor=focused
            else:
                selected=[iid for iid in self.tree.selection() if iid in children]
                anchor=selected[0] if selected else row
            self.anchor=anchor
        start,end=sorted((children.index(anchor),children.index(row)))
        range_items=children[start:end+1]
        if additive:
            merged=list(dict.fromkeys([*self.tree.selection(),*range_items]))
            self.tree.selection_set(merged)
        else:
            self.tree.selection_set(range_items)
        self.tree.focus(row)
        self.tree.see(row)
        return "break"
    def press(self,e:tk.Event):
        self.start_x=e.x; self.start_y=e.y; self.dragging=False
        self.ctrl=bool(e.state & self.CTRL_MASK)
        shift=bool(e.state & self.SHIFT_MASK)
        row=self.tree.identify_row(e.y)
        if row and shift:
            # Handle range selection ourselves and suppress ttk's platform-
            # dependent anchor handling.  Crucially, do not replace our anchor
            # with the Shift-clicked row before calculating the range.
            self.base=self.tree.selection()
            return self._select_range(row, additive=self.ctrl)
        if row:
            # A normal/Ctrl click becomes the anchor for the next Shift-click.
            # ttk still performs the ordinary selection/toggle after this
            # widget binding returns.
            self.anchor=row
        # Explorer behavior: a normal click on blank list space clears the
        # previous selection. Ctrl+blank is kept so Ctrl-drag can add another
        # rectangle to the existing selection.
        if not row and not self.ctrl:
            current=self.tree.selection()
            if current:
                self.tree.selection_remove(current)
            self.anchor=None
        self.base=self.tree.selection()
    def _make_overlay(self):
        try:
            ov=tk.Toplevel(self.tree); ov.overrideredirect(True); ov.attributes("-topmost",True); ov.attributes("-alpha",0.22); ov.configure(bg=COLORS["blue"]); self.overlay=ov
        except Exception: self.overlay=None
    def motion(self,e:tk.Event):
        if not self.dragging and abs(e.x-self.start_x)+abs(e.y-self.start_y)<8: return
        if not self.dragging:
            self.dragging=True; self._make_overlay()
        x1,y1=self.start_x,self.start_y; x2,y2=e.x,e.y
        if self.overlay:
            sx=self.tree.winfo_rootx()+min(x1,x2); sy=self.tree.winfo_rooty()+min(y1,y2); w=max(2,abs(x2-x1)); h=max(2,abs(y2-y1))
            self.overlay.geometry(f"{w}x{h}+{sx}+{sy}")
        top,bottom=sorted((y1,y2)); hits=[]
        for iid in self.tree.get_children():
            bbox=self.tree.bbox(iid)
            if not bbox: continue
            _,ry,_,rh=bbox
            if ry+rh>=top and ry<=bottom: hits.append(iid)
        if self.ctrl: hits=list(dict.fromkeys([*self.base,*hits]))
        self.tree.selection_set(hits)
        return "break"
    def release(self,_e:tk.Event):
        if self.overlay:
            try:self.overlay.destroy()
            except Exception:pass
        self.overlay=None; self.dragging=False

class RDModernApp(AppController):
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.store = SecretStore()
        self.language = normalize_language(self.store.public.language)
        self.store.public.language = self.language
        self.store.public.max_simultaneous_downloads = max(
            1,
            min(MAX_SAFE_SIMULTANEOUS_DOWNLOADS, int(getattr(self.store.public, "max_simultaneous_downloads", 3) or 3)),
        )
        self.api = RealDebridAPI(self.store)
        self.ui_queue = queue.Queue()
        self.torrent_refreshing = False
        self.history_refreshing = False
        self.delete_in_progress = False
        self.upload_in_progress = False
        self.upload_queue_window = None
        self.last_unrestricted: list[dict[str, Any]] = []
        self.pending_folder_links: list[str] = []
        self.local_status_state: dict[int, str] = {}
        self.torrent_data: dict[str, dict[str, Any]] = {}
        self.history_data: dict[str, dict[str, Any]] = {}

        self.download_jobs: dict[int, dict[str, Any]] = {}
        self.download_controls: dict[int, dict[str, Any]] = {}
        self.download_threads: dict[int, threading.Thread] = {}
        self.download_lock = threading.RLock()
        self.download_counter = 0
        self.download_stop = threading.Event()
        self.download_wakeup = threading.Event()
        self.closing = False
        self.download_store = DownloadJobStore(DOWNLOADS_FILE)
        self._load_download_jobs()

        root.title("RD Desktop")
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.configure(bg=COLORS["bg"])
        self._configure_theme()
        apply_windows_titlebar(root)
        root.geometry(f"{theme.px(1280)}x{theme.px(820)}")
        root.minsize(theme.px(1020), theme.px(680))
        self._build_ui()
        self.root.report_callback_exception = self._tk_exception
        self.root.after(50, self._drain_ui_queue)
        self.root.after(150, self.ensure_login)
        self.root.after(5000, self._auto_refresh)
        self.download_scheduler = threading.Thread(
            target=self._download_scheduler_loop,
            daemon=True,
            name="RDDownloadScheduler",
        )
        self.download_scheduler.start()
        self._native_drop_queue: queue.SimpleQueue[tuple[str, ...]] = queue.SimpleQueue()
        self._native_drop_poll_after: str | None = None
        self._enable_windows_file_drop()

    # ---------- modern shell ----------
    def _page_header(self, parent: tk.Misc, title: str, subtitle: str = "", icon: str | None = None) -> tk.Frame:
        f = tk.Frame(parent, bg=COLORS["bg"])
        f.pack(fill="x", padx=theme.px(28), pady=(theme.px(32), theme.px(24)))
        words = tk.Frame(f, bg=COLORS["bg"])
        words.pack(side="left", fill="x", expand=True)
        title_row = tk.Frame(words, bg=COLORS["bg"])
        title_row.pack(anchor="w")
        if icon:
            tk.Label(title_row, image=icon_image(f, icon, theme.px(24), COLORS["green"]), bg=COLORS["bg"], bd=0).pack(side="left", padx=(0, theme.px(12)))
        tk.Label(title_row, text=title, bg=COLORS["bg"], fg=COLORS["text"], font=theme.font(23, True)).pack(side="left")
        if subtitle:
            hint = tk.Label(words, text=subtitle, bg=COLORS["bg"], fg=COLORS["muted"], font=theme.font(9), anchor="w", justify="left")
            hint.pack(anchor="w", pady=(theme.px(7), 0), fill="x")
            words.bind("<Configure>", lambda e: hint.configure(wraplength=max(1, e.width)))
        return f

    def _build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg=COLORS["sidebar"], width=theme.px(228))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(shell, width=1, bg=COLORS["border"]).pack(side="left", fill="y")
        content = tk.Frame(shell, bg=COLORS["bg"])
        content.pack(side="left", fill="both", expand=True)
        brand = tk.Frame(sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=theme.px(20), pady=(theme.px(30), theme.px(34)))
        mark = tk.Canvas(brand, width=theme.px(38), height=theme.px(38), bg=COLORS["sidebar"], bd=0, highlightthickness=0)
        mark.pack(side="left", padx=(0, theme.px(10)))
        _rounded_shape(mark, 0, 0, theme.px(38), theme.px(38), theme.px(10), fill=COLORS["green_button"])
        mark.create_text(theme.px(19), theme.px(19), text="RD", font=theme.font(11, True), fill=COLORS["primary_text"])
        name = tk.Frame(brand, bg=COLORS["sidebar"])
        name.pack(side="left")
        tk.Label(name, text="RD Desktop", bg=COLORS["sidebar"], fg=COLORS["text"], font=theme.font(12, True)).pack(anchor="w")
        tk.Label(name, text="REAL-DEBRID", bg=COLORS["sidebar"], fg=COLORS["muted"], font=theme.font(7)).pack(anchor="w", pady=(theme.px(3), 0))
        tk.Label(sidebar, text=self.t("workspace_label"), bg=COLORS["sidebar"], fg=COLORS["muted"], font=theme.font(8, True)).pack(anchor="w", padx=theme.px(24), pady=(0, theme.px(10)))
        nav = tk.Frame(sidebar, bg=COLORS["sidebar"])
        nav.pack(fill="x", padx=theme.px(12))
        self.sidebar_user = tk.StringVar(value="Real-Debrid")
        bottom = tk.Frame(sidebar, bg=COLORS["sidebar"])
        bottom.pack(side="bottom", fill="x", padx=theme.px(12), pady=theme.px(14))
        hint = self.t("connected_account") if self.api.authenticated else self.t("account_disconnected")
        self.sidebar_account_card = SidebarAccountCard(bottom, self.sidebar_user, hint, lambda: self._open_account_page())
        self.sidebar_account_card.pack(fill="x")
        tk.Label(bottom, text=f"RD Desktop  /  v{APP_VERSION}", bg=COLORS["sidebar"], fg=COLORS["muted"], font=theme.font(8)).pack(anchor="w", padx=theme.px(10), pady=(theme.px(14), 0))
        status = tk.Frame(content, bg=COLORS["bg"], height=theme.px(34))
        status.pack(side="bottom", fill="x")
        status.pack_propagate(False)
        tk.Frame(status, bg=COLORS["border"], height=1).pack(side="top", fill="x")
        self.status_var = tk.StringVar(value=self.t("ready"))
        self.speed_summary_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self.status_var, bg=COLORS["bg"], fg=COLORS["muted"], anchor="w", padx=theme.px(28), font=theme.font(8)).pack(side="left", fill="both", expand=True)
        tk.Label(status, textvariable=self.speed_summary_var, bg=COLORS["bg"], fg=COLORS["blue"], padx=theme.px(28), font=theme.font(8)).pack(side="right")
        self.nb = SidebarBook(content, nav)
        self.nb.pack(fill="both", expand=True)
        self._build_unrestrict_tab()
        self._build_torrents_tab()
        self._build_local_tab()
        self._build_history_tab()
        self._build_account_tab()
        self._build_settings_tab()
        # Settings is a separate group at the foot of the navigation list.
        self.nb.buttons[-1].pack_configure(pady=(theme.px(24), 0))

    def _open_account_page(self) -> None:
        index=getattr(self,"account_page_index",None)
        if index is not None:
            self.nb.select(index)
            if self.api.authenticated:self.refresh_account()

    def _change_language(self, language: str) -> None:
        language = normalize_language(language)
        if language == self.language:
            return
        page = getattr(self.nb, "_current", 0)
        draft_links = self.link_input.get("1.0", "end-1c") if hasattr(self, "link_input") else ""
        draft_password = self.link_password.get() if hasattr(self, "link_password") else ""
        draft_remote = bool(self.remote_var.get()) if hasattr(self, "remote_var") else False
        result_text = self.link_result.get("1.0", "end-1c") if hasattr(self, "link_result") else ""

        self.language = language
        self.store.public.language = language
        self.store.save()
        for child in list(self.root.winfo_children()):
            child.destroy()
        self._build_ui()
        self.nb.select(min(page, len(self.nb.pages) - 1))
        if draft_links:
            self.link_input.insert("1.0", draft_links)
        self.link_password.set(draft_password)
        self.remote_var.set(draft_remote)
        if result_text:
            self.link_result.insert("1.0", result_text)
        self._render_all_download_jobs()
        if self.api.authenticated:
            self.refresh_all()

    def _enable_tree_sorting(self, tree: ttk.Treeview, providers: dict[str, Callable[[str], Any]]) -> None:
        """Make Treeview headings sort their rows using raw data providers."""
        titles = {column: str(tree.heading(column, "text")) for column in tree["columns"]}
        tree._rd_sort_titles = titles  # type: ignore[attr-defined]
        tree._rd_sort_providers = providers  # type: ignore[attr-defined]
        tree._rd_sort_column = None  # type: ignore[attr-defined]
        tree._rd_sort_descending = False  # type: ignore[attr-defined]
        for column in tree["columns"]:
            tree.heading(column, command=lambda c=column, t=tree: self._sort_tree(t, c))

    @staticmethod
    def _sortable_value(value: Any) -> Any:
        if isinstance(value, str):
            return value.casefold()
        return value

    def _apply_tree_sort(self, tree: ttk.Treeview, column: str, descending: bool) -> None:
        providers = getattr(tree, "_rd_sort_providers", {})
        provider = providers.get(column)
        if provider is None:
            return
        present: list[tuple[Any, int, str]] = []
        missing: list[tuple[int, str]] = []
        for index, iid in enumerate(tree.get_children("")):
            try:
                value = provider(str(iid))
            except Exception:
                logging.exception("Could not produce sort key for column=%s iid=%s", column, iid)
                value = None
            if value is None or value == "":
                missing.append((index, str(iid)))
            else:
                present.append((self._sortable_value(value), index, str(iid)))
        # The index is a stable tie breaker. Missing values stay at the bottom in
        # both directions instead of jumping to the top when descending.
        present.sort(key=lambda item: item[0], reverse=descending)
        ordered = [iid for _value, _index, iid in present] + [iid for _index, iid in missing]
        for position, iid in enumerate(ordered):
            tree.move(iid, "", position)
        tree._rd_sort_column = column  # type: ignore[attr-defined]
        tree._rd_sort_descending = bool(descending)  # type: ignore[attr-defined]
        titles = getattr(tree, "_rd_sort_titles", {})
        for key in tree["columns"]:
            title = titles.get(key, str(tree.heading(key, "text")).rstrip(" ▲▼"))
            suffix = " ▼" if key == column and descending else " ▲" if key == column else ""
            tree.heading(key, text=title + suffix)

    def _sort_tree(self, tree: ttk.Treeview, column: str) -> None:
        current = getattr(tree, "_rd_sort_column", None)
        descending = not bool(getattr(tree, "_rd_sort_descending", False)) if current == column else False
        self._apply_tree_sort(tree, column, descending)

    def _reapply_tree_sort(self, tree: ttk.Treeview) -> None:
        column = getattr(tree, "_rd_sort_column", None)
        if column:
            self._apply_tree_sort(tree, column, bool(getattr(tree, "_rd_sort_descending", False)))

    def _tree_with_scroll(self, parent: tk.Misc, columns: list[tuple[str, str, int, str]], *, empty_title: str = "", empty_help: str = "") -> ttk.Treeview:
        panel = RoundedPanel(parent, padding=6)
        panel.pack(fill="both", expand=True)
        frame = panel.inner
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="extended")
        for key, title, width, anchor in columns:
            tree.heading(key, text=title, anchor=anchor)
            heading_width = tkfont.Font(self.root, font=theme.font(9, True)).measure(title) + theme.px(16)
            tree.column(key, width=max(theme.px(width), heading_width), minwidth=theme.px(60), anchor=anchor, stretch=(key in {"name", "path", "url"}))
        y = ModernScrollbar(frame, orient="vertical", command=tree.yview)
        x = ModernScrollbar(frame, orient="horizontal", command=tree.xview)
        empty = tk.Frame(tree, bg=COLORS["panel"])
        tk.Label(empty, image=icon_image(empty, "inbox", theme.px(38), COLORS["muted"]), bg=COLORS["panel"], bd=0).pack(pady=(0, theme.px(14)))
        tk.Label(empty, text=empty_title, bg=COLORS["panel"], fg=COLORS["text"], font=theme.font(12, True)).pack()
        help_label = tk.Label(empty, text=empty_help, bg=COLORS["panel"], fg=COLORS["muted"], font=theme.font(9), justify="center", wraplength=theme.px(440))
        help_label.pack(pady=(theme.px(7), 0))

        def refresh_empty() -> None:
            populated = bool(tree.get_children())
            if populated:
                empty.place_forget()
            elif empty_title:
                empty.place(relx=.5, rely=.48, anchor="center")

        def yset(first, last):
            y.set(first, last) if tree.get_children() else y.set(0, 1)
            refresh_empty()

        def xset(first, last):
            x.set(first, last) if tree.get_children() else x.set(0, 1)

        tree.configure(yscrollcommand=yset, xscrollcommand=xset)
        tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.bind("<Configure>", lambda e: (help_label.configure(wraplength=max(theme.px(100), e.width-theme.px(60))), refresh_empty()), add="+")
        tree._rd_empty = empty
        tree._rd_refresh_empty = refresh_empty

        original_insert = tree.insert
        original_delete = tree.delete
        def insert(*args: Any, **kwargs: Any):
            iid = original_insert(*args, **kwargs)
            tree.after_idle(refresh_empty)
            return iid
        def delete(*items: Any):
            result = original_delete(*items)
            tree.after_idle(refresh_empty)
            return result
        tree.insert = insert  # type: ignore[method-assign]
        tree.delete = delete  # type: ignore[method-assign]

        refresh_empty()
        RubberBandSelector(tree)
        return tree

    # ---------- page builders ----------
    def _build_unrestrict_tab(self) -> None:
        tab = tk.Frame(self.nb, bg=COLORS["bg"])
        self.nb.add(tab, text=self.t("tab_unrestrict"))
        self._page_header(tab, self.t("tab_unrestrict"), self.t("unrestrict_page_subtitle"), "link")
        panel = RoundedPanel(tab, padding=20, fit_content=True)
        panel.pack(fill="x", padx=theme.px(28), pady=(0, theme.px(18)))
        body = panel.inner
        tk.Label(body, text=self.t("paste_links"), bg=COLORS["panel"], fg=COLORS["text"], font=theme.font(10, True)).pack(anchor="w")
        self.link_input = style_text_widget(tk.Text(body, height=4, wrap="word"))
        self.link_input.pack(fill="x", pady=(theme.px(12), theme.px(16)))
        form = tk.Frame(body, bg=COLORS["panel"])
        form.pack(fill="x", pady=(0, theme.px(16)))
        password = tk.Frame(form, bg=COLORS["panel"])
        password.pack(side="left", fill="x", expand=True)
        tk.Label(password, text=self.t("optional_password"), bg=COLORS["panel"], fg=COLORS["muted"], font=theme.font(9)).pack(anchor="w", pady=(0, theme.px(7)))
        self.link_password = tk.StringVar()
        ttk.Entry(password, textvariable=self.link_password, show="*",style="Panel.TEntry").pack(fill="x")
        self.remote_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text=self.t("remote_traffic"), variable=self.remote_var, style="Panel.TCheckbutton").pack(side="left", padx=(theme.px(20), 0), anchor="s", pady=theme.px(7))
        row = FlowRow(body)
        row.pack(fill="x")
        row.add(rd_button(row, self.t("unrestrict"), self.unrestrict_manual, kind="primary", icon="link"))
        row.add(rd_button(row, self.t("expand_folder"), self.unrestrict_folder, kind="neutral", icon="folder"))
        result_panel = RoundedPanel(tab, padding=20)
        result_panel.pack(fill="both", expand=True, padx=theme.px(28), pady=(0, theme.px(24)))
        result_header = tk.Frame(result_panel.inner, bg=COLORS["panel"])
        result_header.pack(fill="x", pady=(0, theme.px(12)))
        tk.Label(result_header, text=self.t("direct_links_title"), bg=COLORS["panel"], fg=COLORS["text"], font=theme.font(11, True)).pack(side="left")
        rd_button(result_header, self.t("download_results"), self.download_manual_results, kind="neutral", icon="download").pack(side="right")
        self.link_result = style_text_widget(tk.Text(result_panel.inner, height=6, wrap="word"))
        self.link_result.pack(fill="both", expand=True)

    def _build_torrents_tab(self)->None:
        tab=tk.Frame(self.nb,bg=COLORS["bg"]); self.nb.add(tab,text=self.t("tab_torrents")); hdr=self._page_header(tab,self.t("tab_torrents"),self.t("torrents_page_subtitle"),"torrent")
        rd_button(hdr,self.t("refresh"),self.refresh_torrents,kind="neutral",icon="refresh").pack(side="right")
        addcard=RoundedPanel(tab,radius=12,padding=20); addcard.configure(height=theme.px(108)); addcard.pack(fill="x",padx=theme.px(28),pady=(0,12)); row=tk.Frame(addcard.inner,bg=COLORS["panel"]); row.pack(fill="both",expand=True)
        self.upload_torrent_btn=rd_button(row,self.t("upload_torrents"),self.add_torrent_file,kind="primary",icon="upload"); self.upload_torrent_btn.pack(side="left")
        self.add_magnet_btn=rd_button(row,self.t("add_magnets"),self.add_magnet,kind="neutral",icon="magnet"); self.add_magnet_btn.pack(side="left",padx=8)
        drop_hint=tk.Label(row,text=self.t("drop_torrents_hint" if os.name == "nt" else "upload_torrents_hint"),bg=COLORS["panel"],fg=COLORS["muted"],font=theme.font(9),justify="left",anchor="w")
        drop_hint.pack(side="left",fill="x",expand=True,padx=theme.px(20))
        row.bind("<Configure>",lambda e:drop_hint.configure(wraplength=max(1,e.width-self.upload_torrent_btn.winfo_reqwidth()-self.add_magnet_btn.winfo_reqwidth()-theme.px(56))))
        actions=FlowRow(tab); actions.pack(fill="x",padx=theme.px(28),pady=(0,8))
        actions.add(rd_button(actions,self.t("choose_files"),self.choose_files,kind="neutral",icon="files"))
        actions.add(rd_button(actions,self.t("get_direct_links"),self.get_direct_links,kind="neutral",icon="direct"))
        actions.add(rd_button(actions,self.t("download_selected"),self.download_torrent,kind="primary",icon="download"))
        self.delete_torrent_btn=rd_button(actions,self.t("delete_selected"),self.delete_torrents,kind="danger",icon="trash"); actions.add(self.delete_torrent_btn)
        holder=tk.Frame(tab,bg=COLORS["bg"]); holder.pack(fill="both",expand=True,padx=theme.px(28),pady=(0,theme.px(24)))
        self.torrent_tree=self._tree_with_scroll(holder,[("name",self.t("col_name"),300,"w"),("status",self.t("col_status"),140,"w"),("progress",self.t("col_progress"),80,"e"),("size",self.t("col_size"),100,"e"),("speed",self.t("col_speed"),100,"e"),("seeders",self.t("col_seeders"),70,"e"),("added",self.t("col_added"),158,"w")],empty_title=self.t("empty_torrents"),empty_help=self.t("empty_torrents_help"))
        for tag,color in (("complete",COLORS["text"]),("active",COLORS["blue"]),("error",COLORS["red"]),("idle",COLORS["muted"])): self.torrent_tree.tag_configure(tag,foreground=color)
        self._enable_tree_sorting(self.torrent_tree,{
            "name":lambda iid:str(self.torrent_data.get(iid,{}).get("filename","")).casefold(),
            "status":lambda iid:str(self.torrent_data.get(iid,{}).get("status","")).casefold(),
            "progress":lambda iid:_numeric_sort_key(self.torrent_data.get(iid,{}).get("progress")),
            "size":lambda iid:_numeric_sort_key(self.torrent_data.get(iid,{}).get("bytes")),
            "speed":lambda iid:_numeric_sort_key(self.torrent_data.get(iid,{}).get("speed")),
            "seeders":lambda iid:_numeric_sort_key(self.torrent_data.get(iid,{}).get("seeders")),
            "added":lambda iid:_timestamp_sort_key(self.torrent_data.get(iid,{}).get("added")),
        })
        self._bind_context_menu(self.torrent_tree, self._torrent_context)

    def _build_local_tab(self)->None:
        tab=tk.Frame(self.nb,bg=COLORS["bg"]); self.nb.add(tab,text=self.t("downloads_nav")); hdr=self._page_header(tab,self.t("downloads_nav"),self.t("downloads_page_subtitle"),"download")
        self.download_count_var=tk.StringVar(value=""); tk.Label(hdr,textvariable=self.download_count_var,bg=COLORS["bg"],fg=COLORS["muted"],font=theme.font(9)).pack(side="right",pady=10)
        actions=FlowRow(tab); actions.pack(fill="x",padx=theme.px(28),pady=(0,10))
        self.pause_btn=rd_button(actions,self.t("pause"),self.pause_local_download,kind="neutral",icon="pause"); actions.add(self.pause_btn)
        self.resume_btn=rd_button(actions,self.t("resume"),self.resume_local_download,kind="primary",icon="resume"); actions.add(self.resume_btn)
        self.cancel_btn=rd_button(actions,self.t("cancel_selected"),self.cancel_local_download,kind="danger",icon="cancel"); actions.add(self.cancel_btn)
        self.remove_btn=rd_button(actions,self.t("remove"),self.remove_local_download,kind="neutral",icon="remove"); actions.add(self.remove_btn)
        self.retry_btn=rd_button(actions,self.t("retry"),self.retry_local_download,kind="secondary",icon="retry"); actions.add(self.retry_btn)
        self.locate_btn=rd_button(actions,self.t("locate_file"),self.locate_missing_file,kind="neutral",icon="locate"); actions.add(self.locate_btn)
        holder=tk.Frame(tab,bg=COLORS["bg"]); holder.pack(fill="both",expand=True,padx=theme.px(28),pady=(0,theme.px(24)))
        self.local_tree=self._tree_with_scroll(holder,[("name",self.t("col_file"),240,"w"),("status",self.t("col_status"),115,"w"),("progress",self.t("col_progress"),75,"e"),("speed",self.t("col_speed"),95,"e"),("eta",self.t("col_eta"),80,"e"),("size",self.t("col_downloaded"),145,"e"),("path",self.t("col_saved_to"),260,"w")],empty_title=self.t("empty_downloads"),empty_help=self.t("empty_downloads_help"))
        for tag,color in (("complete",COLORS["text"]),("active",COLORS["blue"]),("error",COLORS["red"]),("idle",COLORS["muted"]),("paused","#D7B47A" if IS_DARK else "#8A601B"),("missing","#D7B47A" if IS_DARK else "#8A601B")): self.local_tree.tag_configure(tag,foreground=color)
        def local_job(iid:str)->dict[str,Any]:
            try:return self.download_jobs.get(int(iid),{})
            except (TypeError,ValueError):return {}
        self._enable_tree_sorting(self.local_tree,{
            "name":lambda iid:str(local_job(iid).get("name","")).casefold(),
            "status":lambda iid:str(local_job(iid).get("status","")).casefold(),
            "progress":lambda iid:(float(local_job(iid).get("downloaded",0) or 0)/float(local_job(iid).get("total",0) or 1)),
            "speed":lambda iid:_numeric_sort_key(local_job(iid).get("speed")),
            "eta":lambda iid:_numeric_sort_key(local_job(iid).get("eta")),
            "size":lambda iid:_numeric_sort_key(local_job(iid).get("downloaded")),
            "path":lambda iid:str(local_job(iid).get("dest","")).casefold(),
        })
        self.local_tree.bind("<<TreeviewSelect>>",lambda _e:self._update_download_action_buttons())
        self._bind_context_menu(self.local_tree, self._local_context)
        self.local_tree.bind("<Double-1>",self._local_double_click,add="+")
        self._render_all_download_jobs(); self._update_download_action_buttons()

    def _build_history_tab(self)->None:
        tab=tk.Frame(self.nb,bg=COLORS["bg"]); self.nb.add(tab,text=self.t("tab_rd_downloads")); hdr=self._page_header(tab,self.t("tab_rd_downloads"),self.t("history_page_subtitle"),"history")
        rd_button(hdr,self.t("refresh"),self.refresh_history,kind="neutral",icon="refresh").pack(side="right")
        actions=FlowRow(tab); actions.pack(fill="x",padx=theme.px(28),pady=(0,8)); actions.add(rd_button(actions,self.t("download_selected"),self.redownload_history,kind="primary",icon="download")); actions.add(rd_button(actions,self.t("delete_selected_history"),self.delete_history,kind="danger",icon="trash"))
        holder=tk.Frame(tab,bg=COLORS["bg"]); holder.pack(fill="both",expand=True,padx=theme.px(28),pady=(0,theme.px(24))); self.history_tree=self._tree_with_scroll(holder,[("name",self.t("col_filename"),300,"w"),("host",self.t("col_host"),110,"w"),("size",self.t("col_size"),100,"e"),("generated",self.t("col_generated"),180,"w"),("url",self.t("col_download_url"),260,"w")],empty_title=self.t("empty_history"),empty_help=self.t("empty_history_help")); self.history_data={}
        self._enable_tree_sorting(self.history_tree,{
            "name":lambda iid:str(self.history_data.get(iid,{}).get("filename","")).casefold(),
            "host":lambda iid:str(self.history_data.get(iid,{}).get("host","")).casefold(),
            "size":lambda iid:_numeric_sort_key(self.history_data.get(iid,{}).get("filesize")),
            "generated":lambda iid:_timestamp_sort_key(self.history_data.get(iid,{}).get("generated")),
            "url":lambda iid:str(self.history_data.get(iid,{}).get("download","")).casefold(),
        })

    def _build_account_tab(self) -> None:
        tab = tk.Frame(self.nb, bg=COLORS["bg"])
        self.account_page_index = len(self.nb.pages)
        self.nb.add(tab, text=self.t("tab_account"))
        self.nb.buttons[self.account_page_index].pack_forget()
        self._page_header(tab, self.t("tab_account"), self.t("account_page_subtitle"), "user")
        panel = RoundedPanel(tab, padding=24, fit_content=True)
        panel.pack(fill="x", padx=theme.px(28), pady=(0, theme.px(18)))
        body = panel.inner
        tk.Label(body, text=self.t("account_details_title"), bg=COLORS["panel"], fg=COLORS["text"], font=theme.font(12, True)).grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,theme.px(12)))
        self.account_fields = {}
        for i, key in enumerate(("account_username", "account_email", "account_type", "premium_expiration", "fidelity_points", "locale", "active_torrents", "auth_mode")):
            cell = tk.Frame(body, bg=COLORS["panel"])
            cell.grid(row=i//2+1,column=i%2,sticky="ew",padx=(0,theme.px(24)),pady=theme.px(10))
            tk.Label(cell,text=self.t(key),bg=COLORS["panel"],fg=COLORS["muted"],font=theme.font(9),anchor="w").pack(fill="x")
            var = tk.StringVar(value="—")
            value = tk.Label(cell,textvariable=var,bg=COLORS["panel"],fg=COLORS["text"],font=theme.font(10,True),anchor="w",justify="left")
            value.pack(fill="x",pady=(theme.px(6),0))
            cell.bind("<Configure>",lambda e,label=value:label.configure(wraplength=max(1,e.width)))
            self.account_fields[key] = var
        body.columnconfigure(0,weight=1,uniform="details")
        body.columnconfigure(1,weight=1,uniform="details")
        authorization = RoundedPanel(tab,padding=20,fit_content=True)
        authorization.pack(fill="x",padx=theme.px(28),pady=(0,theme.px(24)))
        tk.Label(authorization.inner,text=self.t("device_access_title"),bg=COLORS["panel"],fg=COLORS["text"],font=theme.font(11,True)).pack(anchor="w",pady=(0,theme.px(14)))
        row = FlowRow(authorization.inner)
        row.pack(fill="x")
        row.add(rd_button(row,self.t("refresh_account"),self.refresh_account,kind="neutral",icon="refresh"))
        row.add(rd_button(row,self.t("authorization"),self.open_login,kind="primary",icon="user"))
        row.add(rd_button(row,self.t("forget_local_authorization"),self.logout,kind="danger",icon="trash"))
        # Keep the backing text model for existing refresh integrations.
        self.account_text = tk.Text(tab,state="disabled")

    def _build_settings_tab(self)->None:
        tab=tk.Frame(self.nb,bg=COLORS["bg"]); self.nb.add(tab,text=self.t("settings")); self._page_header(tab,self.t("settings"),self.t("settings_page_subtitle"),"settings")
        panel=RoundedPanel(tab,radius=12,padding=24,fit_content=True); panel.pack(fill="x",padx=theme.px(28),pady=(0,14)); body=panel.inner
        tk.Label(body,text=self.t("default_save_folder"),bg=COLORS["panel"],fg=COLORS["text"],font=theme.font(10,True)).pack(anchor="w")
        tk.Label(body,text=self.t("default_save_folder_help"),bg=COLORS["panel"],fg=COLORS["muted"],font=theme.font(9)).pack(anchor="w",pady=(2,7))
        fr=tk.Frame(body,bg=COLORS["panel"]); fr.pack(fill="x"); self.download_dir_var=tk.StringVar(value=self.store.public.download_dir); ttk.Entry(fr,textvariable=self.download_dir_var,state="readonly",style="Panel.TEntry").pack(side="left",fill="x",expand=True); rd_button(fr,self.t("browse"),self._choose_default_folder,kind="neutral",icon="folder").pack(side="left",padx=(8,0))
        sep=tk.Frame(body,bg=COLORS["border"],height=1); sep.pack(fill="x",pady=theme.px(24))
        auto=tk.Frame(body,bg=COLORS["panel"]); auto.pack(fill="x"); texts=tk.Frame(auto,bg=COLORS["panel"]); texts.pack(side="left",fill="x",expand=True); tk.Label(texts,text=self.t("auto_select_all"),bg=COLORS["panel"],fg=COLORS["text"],font=theme.font(10,True)).pack(anchor="w"); tk.Label(texts,text=self.t("auto_select_help"),bg=COLORS["panel"],fg=COLORS["muted"],font=theme.font(9)).pack(anchor="w",pady=(2,0)); self.auto_select_var=tk.BooleanVar(value=self.store.public.auto_select_all); ToggleSwitch(auto,self.auto_select_var,self._save_auto_select).pack(side="right")
        sep=tk.Frame(body,bg=COLORS["border"],height=1); sep.pack(fill="x",pady=theme.px(24))
        conc=tk.Frame(body,bg=COLORS["panel"]); conc.pack(fill="x"); self.download_limit_row=conc; txt=tk.Frame(conc,bg=COLORS["panel"]); txt.pack(side="left",fill="x",expand=True); tk.Label(txt,text=self.t("simultaneous_downloads"),bg=COLORS["panel"],fg=COLORS["text"],font=theme.font(10,True)).pack(anchor="w"); tk.Label(txt,text=self.t("simultaneous_help",max=MAX_SAFE_SIMULTANEOUS_DOWNLOADS),bg=COLORS["panel"],fg=COLORS["muted"],font=theme.font(9)).pack(anchor="w",pady=(2,0)); controls=tk.Frame(conc,bg=COLORS["panel"]); controls.pack(side="right"); self.download_limit_stepper=NumberStepper(controls,self.store.public.max_simultaneous_downloads,self._set_download_limit,self._show_download_limit_warning); self.download_limit_stepper.pack(side="left")
        sep=tk.Frame(body,bg=COLORS["border"],height=1); sep.pack(fill="x",pady=theme.px(24))
        lang=tk.Frame(body,bg=COLORS["panel"]); lang.pack(fill="x"); langtxt=tk.Frame(lang,bg=COLORS["panel"]); langtxt.pack(side="left",fill="x",expand=True); tk.Label(langtxt,text=self.t("interface_language"),bg=COLORS["panel"],fg=COLORS["text"],font=theme.font(10,True)).pack(anchor="w"); tk.Label(langtxt,text=self.t("interface_language_help"),bg=COLORS["panel"],fg=COLORS["muted"],font=theme.font(9)).pack(anchor="w",pady=(2,0)); langcontrol=tk.Frame(lang,bg=COLORS["panel"]); langcontrol.pack(side="right"); self._build_language_selector(langcontrol)

    # ---------- settings ----------
    def _choose_default_folder(self)->None:
        path=filedialog.askdirectory(title=self.t("default_save_folder"),initialdir=self.store.public.download_dir)
        if path:self.store.public.download_dir=path;self.store.save();self.download_dir_var.set(path)
    def _set_download_limit(self,value:int)->None:
        value=max(1,min(MAX_SAFE_SIMULTANEOUS_DOWNLOADS,int(value))); self.store.public.max_simultaneous_downloads=value; self.store.save(); self.download_wakeup.set()
    def _show_download_limit_warning(self)->None:
        # A short non-modal reminder positioned directly above the number field.
        old=getattr(self,"_download_limit_warning",None)
        if old is not None:
            try: old.destroy()
            except Exception: pass
        try:
            anchor=self.download_limit_stepper
            anchor.update_idletasks()
            tip=tk.Toplevel(self.root); self._download_limit_warning=tip; tip.overrideredirect(True); tip.attributes("-topmost",True); tip.configure(bg="#7B3035")
            inner=tk.Frame(tip,bg="#7B3035",highlightthickness=1,highlightbackground="#C85B62",padx=10,pady=6); inner.pack(fill="both",expand=True)
            tk.Label(inner,text="⚠  "+self.t("download_limit_warning",min=1,max=MAX_SAFE_SIMULTANEOUS_DOWNLOADS),bg="#7B3035",fg="#FFFFFF",font=theme.font(9, True)).pack()
            tip.update_idletasks(); x=anchor.winfo_rootx()+anchor.winfo_width()-tip.winfo_reqwidth(); y=anchor.winfo_rooty()-tip.winfo_reqheight()-7; tip.geometry(f"+{max(0,x)}+{max(0,y)}")
            def close_tip():
                if getattr(self,"_download_limit_warning",None) is tip:self._download_limit_warning=None
                try: tip.destroy()
                except Exception: pass
            tip.after(2400,close_tip)
        except Exception:
            logging.exception("Could not show download-limit reminder")
    def _save_auto_select(self)->None:
        self.store.public.auto_select_all=bool(self.auto_select_var.get()); self.store.save()

    # ---------- refresh overrides ----------
    def refresh_torrents(self,silent:bool=False)->None:
        if not self.api.authenticated or self.delete_in_progress or self.upload_in_progress or self.torrent_refreshing:return
        self.torrent_refreshing=True
        def done(rows):
            self.torrent_refreshing=False; self.torrent_data={str(x.get("id","")):x for x in rows if x.get("id")}; selected=set(self.torrent_tree.selection()); self.torrent_tree.delete(*self.torrent_tree.get_children())
            for t in rows:
                tid=str(t.get("id","") or "");
                if not tid:continue
                raw=str(t.get("status","") or ""); tag="complete" if raw=="downloaded" else "active" if raw in {"downloading","magnet_conversion","waiting_files_selection","queued","compressing","uploading"} else "error" if raw in {"error","magnet_error","virus","dead"} else "idle"
                speed=human_bytes(t.get("speed",0))+"/s" if t.get("speed") else ""
                self.torrent_tree.insert("","end",iid=tid,values=(t.get("filename",""),self._torrent_status_text(raw),f"{t.get('progress',0)}%",human_bytes(t.get("bytes",0)),speed,t.get("seeders",""),format_timestamp(t.get("added",""),self.language)),tags=(tag,))
            self._reapply_tree_sort(self.torrent_tree)
            keep=[x for x in selected if self.torrent_tree.exists(x)];
            if keep:self.torrent_tree.selection_set(keep)
        def fail(msg):self.torrent_refreshing=False; (None if silent else messagebox.showerror("Real-Debrid",msg,parent=self.root))
        self.async_call(self.api.torrents,done,fail,busy=None if silent else self.t("refreshing_torrents"))

    def refresh_account(self)->None:
        if not self.api.authenticated:return
        def job():return {"user":self.api.user(),"active":self.api.active_count()}
        def done(data):
            u=data.get("user",{});a=data.get("active",{}); self.sidebar_user.set(str(u.get("username") or "Real-Debrid"))
            lines=[f"{self.t('account_username')}: {u.get('username','')}",f"{self.t('account_email')}: {u.get('email','')}",f"{self.t('account_type')}: {u.get('type','')}",f"{self.t('premium_expiration')}: {format_timestamp(u.get('expiration',''),self.language)}",f"{self.t('fidelity_points')}: {u.get('points','')}",f"{self.t('locale')}: {u.get('locale','')}",f"{self.t('active_torrents')}: {a.get('nb','?')} / {a.get('limit','?')}",f"{self.t('auth_mode')}: {self.store.public.auth_mode or self.t('none')}"]
            self.account_text.configure(state="normal");self.account_text.delete("1.0","end");self.account_text.insert("1.0","\n\n".join(lines));self.account_text.configure(state="disabled")
            values={"account_username":u.get("username","—"),"account_email":u.get("email","—"),"account_type":u.get("type","—"),"premium_expiration":format_timestamp(u.get("expiration",""),self.language) or "—","fidelity_points":u.get("points","—"),"locale":u.get("locale","—"),"active_torrents":f"{a.get('nb','?')} / {a.get('limit','?')}","auth_mode":self.store.public.auth_mode or self.t("none")}
            for key,value in values.items():
                if key in getattr(self,"account_fields",{}):self.account_fields[key].set(str(value))
            self.sidebar_account_card.hint=self.t("connected_account");self.sidebar_account_card._draw()
        self.async_call(job,done,busy=self.t("refreshing_account"))

    # ---------- resilient torrent operations ----------
    def _wait_for_files(self,tid:str,timeout:int=45)->dict[str,Any]:
        deadline=time.time()+timeout;last={}; delays=[.5,1,2,3]; unknown=0
        while time.time()<deadline:
            try:last=self.api.torrent_info(tid)
            except RealDebridError as exc:
                if exc.status==404 or exc.error_code==7:
                    logging.warning("torrent info unknown resource id=%s attempt=%s status=%s code=%s",tid,unknown+1,exc.status,exc.error_code); time.sleep(delays[min(unknown,len(delays)-1)]); unknown+=1; continue
                raise
            if last.get("files"):return last
            if last.get("status") in {"error","dead","virus","magnet_error"}:break
            time.sleep(1.5)
        return last
    def _select_files_resilient(self,tid:str,file_ids:Any)->None:
        delays=[.5,1,2,3]
        for attempt,delay in enumerate(delays,1):
            try:self.api.select_files(tid,file_ids);return
            except RealDebridError as exc:
                logging.warning("selectFiles id=%s attempt=%s status=%s code=%s error=%s",tid,attempt,exc.status,exc.error_code,exc)
                if not (exc.status==404 or exc.error_code==7) or attempt==len(delays):raise
                time.sleep(delay)
                try:self.api.torrent_info(tid)
                except Exception:pass

    # ---------- multi torrent direct/download ----------
    def get_direct_links(self)->None:
        ids=self._selected_torrent_ids()
        if not ids:messagebox.showinfo(self.t("select_torrent_title"),self.t("select_torrents_first"));return
        def job():
            out=[];fails=[]
            for tid in ids:
                try:out.extend(self._unrestrict_torrent_links(tid))
                except Exception as exc:fails.append(f"{tid}: {exc}")
            return out,fails
        def done(result):
            items,fails=result;links=[str(x.get("download","")) for x in items if x.get("download")]
            if links:self.root.clipboard_clear();self.root.clipboard_append("\n".join(links));messagebox.showinfo(self.t("direct_links_title"),self.t("generated_links",count=len(links)),parent=self.root)
            if fails:messagebox.showwarning(self.t("direct_links_title"),"\n".join(fails[:10]),parent=self.root)
        self.async_call(job,done,busy=self.t("generating_direct_links"))
    def download_torrent(self)->None:
        ids=self._selected_torrent_ids()
        if not ids:messagebox.showinfo(self.t("select_torrent_title"),self.t("select_torrents_first"));return
        directory=self.store.public.download_dir
        def job():
            items=[];fails=[]
            for tid in ids:
                try:items.extend(self._unrestrict_torrent_links(tid))
                except Exception as exc:fails.append(f"{self.torrent_data.get(tid,{}).get('filename',tid)}: {exc}")
            return items,fails
        def done(result):
            items,fails=result;self._queue_unrestricted(items,directory)
            if fails:messagebox.showwarning(self.t("downloads_title"),"\n".join(fails[:10]),parent=self.root)
        self.async_call(job,done,busy=self.t("preparing_downloads"))
    def download_manual_results(self) -> None:
        if self.last_unrestricted:
            self._queue_unrestricted(self.last_unrestricted, self.store.public.download_dir)
            return
        folder_links = list(getattr(self, "pending_folder_links", []))
        if not folder_links:
            messagebox.showinfo(self.t("downloads_title"), self.t("unrestrict_first"))
            return

        def job() -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for link in folder_links:
                result = self.api.unrestrict_link(link)
                if isinstance(result, list):
                    items.extend(x for x in result if isinstance(x, dict))
                elif isinstance(result, dict):
                    items.append(result)
            return items

        def done(items: list[dict[str, Any]]) -> None:
            self.last_unrestricted = items
            self.pending_folder_links = []
            self._queue_unrestricted(items, self.store.public.download_dir)

        self.async_call(job, done, busy=self.t("preparing_downloads"))
    def redownload_history(self)->None:
        ids=list(self.history_tree.selection());items=[self.history_data[x] for x in ids if x in self.history_data and self.history_data[x].get("download")]
        if not items:return
        normalized=[{"download":d.get("download",""),"filename":d.get("filename","download.bin"),"filesize":d.get("filesize",0)} for d in items];self._queue_unrestricted(normalized,self.store.public.download_dir)

    # ---------- persistent concurrent local download manager ----------
    def _load_download_jobs(self) -> None:
        try:
            store = getattr(self, "download_store", None) or DownloadJobStore(DOWNLOADS_FILE)
            for raw in store.load():
                did = int(raw.get("id", 0) or 0)
                if did <= 0:
                    continue
                job = reconcile_job(raw)
                self.download_jobs[did] = job
                self.local_status_state[did] = str(job.get("status", "Paused"))
                self.download_counter = max(self.download_counter, did)
        except Exception:
            logging.exception("Failed loading local download queue")
    def _save_download_jobs(self) -> None:
        try:
            with self.download_lock:
                snapshot = {did: dict(job) for did, job in self.download_jobs.items()}
            store = getattr(self, "download_store", None) or DownloadJobStore(DOWNLOADS_FILE)
            store.save(snapshot)
        except Exception:
            logging.exception("Failed saving local download queue")
    def _queue_unrestricted(self,items:list[dict[str,Any]],directory:str)->None:
        count=0
        with self.download_lock:
            for item in items:
                url=str(item.get("download","") or "");
                if not url:continue
                name=safe_filename(str(item.get("filename") or Path(urllib.request.url2pathname(url.split("?")[0])).name or "download.bin"));dest=self._unique_destination(directory,name);self.download_counter+=1;did=self.download_counter
                job={"id":did,"url":url,"dest":dest,"name":name,"status":"Queued","downloaded":0,"total":int(item.get("filesize",0) or 0),"speed":0.0,"eta":None,"error":""};self.download_jobs[did]=job;self.local_status_state[did]="Queued";count+=1
            self._save_download_jobs()
        self._render_all_download_jobs();self.download_wakeup.set()
        if count:self.nb.select(2);self.set_status(self.t("queued_downloads",count=count))
    def _unique_destination(self,directory:str,name:str)->str:
        base=Path(directory)/name; used={str(j.get("dest","")) for j in self.download_jobs.values()}
        if str(base) not in used and not base.exists() and not Path(str(base)+".part").exists(): return str(base)
        stem,suffix=base.stem,base.suffix
        for n in range(2,10000):
            candidate=base.with_name(f"{stem} ({n}){suffix}")
            if str(candidate) not in used and not candidate.exists() and not Path(str(candidate)+".part").exists(): return str(candidate)
        return str(base.with_name(f"{stem}-{int(time.time())}{suffix}"))

    def _download_scheduler_loop(self) -> None:
        while not self.download_stop.is_set():
            self.download_wakeup.wait(.35)
            self.download_wakeup.clear()
            starts: list[tuple[int, dict[str, Any]]] = []
            with self.download_lock:
                active = sum(1 for job in self.download_jobs.values() if job.get("status") == "Downloading")
                limit = max(1, min(MAX_SAFE_SIMULTANEOUS_DOWNLOADS, int(self.store.public.max_simultaneous_downloads)))
                for did, job in sorted(self.download_jobs.items()):
                    if active >= limit:
                        break
                    if job.get("status") != "Queued":
                        continue
                    ctrl = {"stop": threading.Event(), "action": None}
                    self.download_controls[did] = ctrl
                    job["status"] = "Downloading"
                    self.local_status_state[did] = "Downloading"
                    active += 1
                    starts.append((did, ctrl))
                if starts:
                    self._save_download_jobs()
            for did, ctrl in starts:
                self.post(self._render_download_job, did)
                thread = threading.Thread(target=self._download_worker_job, args=(did, ctrl), daemon=True, name=f"RDDownload-{did}")
                with self.download_lock:
                    self.download_threads[did] = thread
                thread.start()
            self.post(self._update_download_summary)
    def _download_worker_job(self, did: int, ctrl: dict[str, Any]) -> None:
        try:
            self._download_one_modern(did, ctrl)
        except Exception as exc:
            self._set_job_state(did, "Failed", error=str(exc) or exc.__class__.__name__, speed=0.0, eta=None)
        finally:
            with self.download_lock:
                self.download_controls.pop(did, None)
                self.download_threads.pop(did, None)
            self.download_wakeup.set()
    def _download_one_modern(self, did: int, ctrl: dict[str, Any]) -> None:
        with self.download_lock:
            job = dict(self.download_jobs.get(did, {}))
        url = str(job.get("url", "") or "")
        dest = str(job.get("dest", "") or "")
        if not url or not dest:
            raise RuntimeError("Download job is missing its URL or destination.")
        expected_total = int(job.get("total", 0) or 0)
        last_save = time.monotonic()

        def stop_action() -> str | None:
            return str(ctrl.get("action") or "cancel") if ctrl["stop"].is_set() else None

        def progress(downloaded: int, total: int, speed: float, eta: float | None) -> None:
            nonlocal last_save
            self._set_job_state(did, "Downloading", downloaded=downloaded, total=total, speed=speed, eta=eta, persist=False)
            now = time.monotonic()
            if now - last_save >= 5:
                self._save_download_jobs()
                last_save = now

        result = download_file(
            url=url,
            destination=dest,
            expected_total=expected_total,
            stop_action=stop_action,
            progress=progress,
        )
        if result.status == "Completed":
            self._set_job_state(did, "Completed", downloaded=result.downloaded, total=result.total, speed=0.0, eta=0, error="")
        else:
            self._set_job_state(did, result.status, downloaded=result.downloaded, total=result.total, speed=0.0, eta=None)
    def _set_job_state(self, did: int, status: str, **changes: Any) -> None:
        persist = changes.pop("persist", True)
        with self.download_lock:
            job = self.download_jobs.get(did)
            if not job:
                return
            job.update(changes)
            job["status"] = status
            self.local_status_state[did] = status
        if persist:
            self._save_download_jobs()
        if not getattr(self, "closing", False):
            self.post(self._render_download_job, did)
            self.post(self._update_download_summary)
    def _render_all_download_jobs(self)->None:
        if not hasattr(self,"local_tree"):return
        self.local_tree.delete(*self.local_tree.get_children())
        for did in sorted(self.download_jobs):self._render_download_job(did)
        self._reapply_tree_sort(self.local_tree)
        self._update_download_summary()
    def _render_download_job(self,did:int)->None:
        if not hasattr(self,"local_tree"):return
        with self.download_lock:
            job=dict(self.download_jobs.get(did,{}) )
        if not job:return
        status=str(job.get("status","Queued"));downloaded=int(job.get("downloaded",0) or 0);total=int(job.get("total",0) or 0);speed=float(job.get("speed",0) or 0);eta=job.get("eta");pct=int(downloaded*100/total) if total else (100 if status in {"Completed","Missing"} else 0);
        if status=="Missing": pct=100
        eta_text=self._format_eta(eta);size=human_bytes(downloaded)+(f" / {human_bytes(total)}" if total else ""); status_text=self._local_status_text(status); err=str(job.get("error","") or "");
        if status=="Failed" and err: status_text=f"{status_text}: {err[:42]}"
        vals=(job.get("name",""),status_text,f"{pct}%",human_bytes(speed)+"/s" if speed>0 else "",eta_text,size,job.get("dest",""));tag="complete" if status=="Completed" else "missing" if status=="Missing" else "active" if status in {"Downloading","Queued"} else "paused" if status=="Paused" else "error" if status in {"Failed","Cancelled"} or status.startswith("Error") else "idle";iid=str(did)
        if self.local_tree.exists(iid):self.local_tree.item(iid,values=vals,tags=(tag,))
        else:self.local_tree.insert("","end",iid=iid,values=vals,tags=(tag,))
        self._update_download_action_buttons()
    def _format_eta(self,value:Any)->str:
        if value is None:return ""
        try:sec=max(0,int(value))
        except Exception:return ""
        if sec<60:return f"{sec}s"
        if sec<3600:return f"{sec//60}m {sec%60:02d}s"
        return f"{sec//3600}h {(sec%3600)//60:02d}m"
    def _update_download_summary(self)->None:
        if not hasattr(self,"speed_summary_var"):return
        with self.download_lock:
            active=[j for j in self.download_jobs.values() if j.get("status")=="Downloading"];queued=sum(1 for j in self.download_jobs.values() if j.get("status")=="Queued");speed=sum(float(j.get("speed",0) or 0) for j in active)
        self.speed_summary_var.set((f"{len(active)} active · {human_bytes(speed)}/s" if active else "")+(f" · {queued} queued" if queued else ""));
        if hasattr(self,"download_count_var"):self.download_count_var.set(f"{len(self.download_jobs)} items")
    def _selected_local_ids(self)->list[int]:
        out=[]
        for iid in self.local_tree.selection():
            try:out.append(int(iid))
            except ValueError:pass
        return out
    def _update_download_action_buttons(self)->None:
        if not hasattr(self,"local_tree"):return
        ids=self._selected_local_ids(); sts=[self.download_jobs.get(i,{}).get("status") for i in ids]
        missing_only=bool(sts) and all(s=="Missing" for s in sts)
        self.retry_btn.configure(text=self.t("redownload") if missing_only else self.t("retry"))
        for btn,ok in ((self.pause_btn,any(s=="Downloading" for s in sts)),(self.resume_btn,any(s=="Paused" for s in sts)),(self.cancel_btn,any(s in {"Queued","Downloading","Paused"} for s in sts)),(self.remove_btn,any(s in {"Completed","Missing","Failed","Cancelled","Paused"} for s in sts)),(self.retry_btn,any(s in {"Missing","Failed","Cancelled"} for s in sts)),(self.locate_btn,len(ids)==1 and sts==["Missing"])):btn.configure(state="normal" if ok else "disabled")
    def pause_local_download(self)->None:
        for did in self._selected_local_ids():
            with self.download_lock:
                job=self.download_jobs.get(did);ctrl=self.download_controls.get(did)
                if job and job.get("status")=="Downloading" and ctrl:ctrl["action"]="pause";ctrl["stop"].set()
    def resume_local_download(self)->None:
        for did in self._selected_local_ids():
            with self.download_lock:
                job=self.download_jobs.get(did)
                if job and job.get("status")=="Paused":job["status"]="Queued";job["error"]="";self.local_status_state[did]="Queued"
            self._render_download_job(did)
        self._save_download_jobs();self.download_wakeup.set()
    def cancel_local_download(self)->None:
        for did in self._selected_local_ids():
            with self.download_lock:
                job=self.download_jobs.get(did);ctrl=self.download_controls.get(did)
                if not job or job.get("status") not in {"Queued","Downloading","Paused"}:continue
                if job.get("status")=="Downloading" and ctrl:ctrl["action"]="cancel";ctrl["stop"].set()
                else:job["status"]="Cancelled";self.local_status_state[did]="Cancelled"
            self._render_download_job(did)
        self._save_download_jobs();self.download_wakeup.set()
    def remove_local_download(self)->None:
        ids=self._selected_local_ids();removed=0
        with self.download_lock:
            for did in ids:
                job=self.download_jobs.get(did)
                if job and job.get("status") in {"Completed","Missing","Failed","Cancelled","Paused"}:self.download_jobs.pop(did,None);self.local_status_state.pop(did,None);removed+=1
            self._save_download_jobs()
        for did in ids:
            if self.local_tree.exists(str(did)) and did not in self.download_jobs:self.local_tree.delete(str(did))
        self._update_download_summary();self._update_download_action_buttons()
    def retry_local_download(self)->None:
        for did in self._selected_local_ids():
            with self.download_lock:
                job=self.download_jobs.get(did)
                if job and job.get("status") in {"Missing","Failed","Cancelled"}:
                    if job.get("status")=="Missing": job["downloaded"]=0
                    job["status"]="Queued";job["error"]="";job["speed"]=0.0;job["eta"]=None;self.local_status_state[did]="Queued"
            self._render_download_job(did)
        self._save_download_jobs();self.download_wakeup.set()
    def locate_missing_file(self) -> None:
        ids = self._selected_local_ids()
        if len(ids) != 1:
            return
        did = ids[0]
        with self.download_lock:
            job = dict(self.download_jobs.get(did, {}))
        if job.get("status") != "Missing":
            return
        current = Path(str(job.get("dest", "") or ""))
        chosen = filedialog.askopenfilename(title=self.t("locate_file"), initialdir=str(current.parent) if str(current.parent) else None, initialfile=current.name or None, parent=self.root)
        if not chosen:
            return
        try:
            size = os.path.getsize(chosen)
        except OSError:
            return
        expected = int(job.get("total", 0) or 0)
        if expected and size != expected:
            messagebox.showerror(self.t("locate_file"), f"Selected file is {human_bytes(size)}, expected {human_bytes(expected)}.", parent=self.root)
            return
        with self.download_lock:
            live = self.download_jobs.get(did)
            if not live:
                return
            live.update(dest=chosen, name=Path(chosen).name, downloaded=size, total=expected or size, status="Completed", error="", speed=0.0, eta=0)
            self.local_status_state[did] = "Completed"
        self._save_download_jobs()
        self._render_download_job(did)
        self._update_download_summary()

    # ---------- context menus / open helpers ----------
    def _bind_context_menu(self, tree: ttk.Treeview, callback: Callable[[tk.Event], str]) -> None:
        tree.bind('<Button-3>', callback, add='+')
        for sequence in ('<Shift-F10>', '<KeyPress-Menu>'):
            tree.bind(sequence, lambda _e, t=tree, cb=callback: self._keyboard_context(t, cb), add='+')

    def _keyboard_context(self, tree: ttk.Treeview, callback: Callable[[tk.Event], str]) -> str:
        selected = tree.selection()
        iid = tree.focus() if tree.focus() in selected else selected[0] if selected else tree.focus()
        if not iid or not tree.exists(iid):
            return 'break'
        tree.see(iid)
        tree.update_idletasks()
        bounds = tree.bbox(iid)
        if not bounds:
            return 'break'
        event = tk.Event()
        event.y = bounds[1] + bounds[3] // 2
        event.x_root = tree.winfo_rootx() + bounds[0] + theme.px(28)
        event.y_root = tree.winfo_rooty() + event.y
        event.context_keyboard = True
        return callback(event)

    def _select_context_row(self,tree:ttk.Treeview,event:tk.Event)->str:
        iid=tree.identify_row(event.y)
        if not iid:
            current=tree.selection()
            if current: tree.selection_remove(current)
            return ""
        if iid not in tree.selection():tree.selection_set(iid)
        return iid
    def _torrent_context(self,event:tk.Event)->str:
        iid=self._select_context_row(self.torrent_tree,event)
        if not iid:return "break"
        menu = ContextMenu(self.torrent_tree)
        menu.add_command(label=self.t('download_selected'), command=self.download_torrent, icon='download')
        menu.add_command(label=self.t('get_direct_links'), command=self.get_direct_links, icon='direct')
        menu.add_command(label=self.t('choose_files'), command=self.choose_files, icon='files',
                         state='normal' if len(self.torrent_tree.selection()) == 1 else 'disabled')
        menu.add_separator()
        menu.add_command(label=self.t('copy_name'), command=self._copy_selected_torrent_name, icon='copy')
        menu.add_command(label=self.t('copy_hash'), command=self._copy_selected_torrent_hash, icon='copy')
        menu.add_separator()
        menu.add_command(label=self.t('remove'), command=self.delete_torrents, icon='trash', kind='danger')
        menu.popup(event.x_root, event.y_root, keyboard=getattr(event, 'context_keyboard', False))
        return 'break'
    def _copy_selected_torrent_name(self):
        ids=self._selected_torrent_ids();
        if ids:self.root.clipboard_clear();self.root.clipboard_append(str(self.torrent_data.get(ids[0],{}).get("filename",self.torrent_tree.item(ids[0],"values")[0])))
    def _copy_selected_torrent_hash(self):
        ids=self._selected_torrent_ids();
        if ids:
            value=str(self.torrent_data.get(ids[0],{}).get("hash","") or "")
            if value:self.root.clipboard_clear();self.root.clipboard_append(value)
    def _local_context(self,event:tk.Event)->str:
        iid=self._select_context_row(self.local_tree,event)
        if not iid:return "break"
        ids = self._selected_local_ids()
        statuses = {self.download_jobs.get(i, {}).get('status') for i in ids}
        menu = ContextMenu(self.local_tree)
        actions = (
            ('pause', self.pause_local_download, 'pause', 'Downloading' in statuses, 'neutral'),
            ('resume', self.resume_local_download, 'resume', 'Paused' in statuses, 'neutral'),
            ('cancel', self.cancel_local_download, 'cancel', bool(statuses & {'Queued', 'Downloading', 'Paused'}), 'danger'),
            ('redownload' if statuses == {'Missing'} else 'retry', self.retry_local_download, 'retry', bool(statuses & {'Missing', 'Failed', 'Cancelled'}), 'neutral'),
            ('locate_file', self.locate_missing_file, 'locate', statuses == {'Missing'} and len(ids) == 1, 'neutral'),
        )
        for key, command, icon, enabled, kind in actions:
            menu.add_command(label=self.t(key), command=command, icon=icon, kind=kind,
                             state='normal' if enabled else 'disabled')
        menu.add_separator()
        menu.add_command(label=self.t('open_file'), command=self._open_selected_file, icon='files',
                         state='normal' if statuses == {'Completed'} and len(ids) == 1 else 'disabled')
        menu.add_command(label=self.t('open_folder'), command=self._open_selected_folder, icon='folder')
        menu.add_command(label=self.t('copy_path'), command=self._copy_selected_path, icon='copy')
        menu.add_separator()
        menu.add_command(label=self.t('remove'), command=self.remove_local_download, icon='remove',
                         state='normal' if statuses & {'Completed', 'Missing', 'Failed', 'Cancelled', 'Paused'} else 'disabled')
        menu.popup(event.x_root, event.y_root, keyboard=getattr(event, 'context_keyboard', False))
        return 'break'
    def _local_double_click(self,event:tk.Event)->None:
        iid=self.local_tree.identify_row(event.y)
        if iid:
            try:
                if self.download_jobs[int(iid)].get("status")=="Completed":self._open_selected_file()
            except Exception:pass
    def _open_selected_file(self) -> None:
        ids = self._selected_local_ids()
        if len(ids) == 1:
            path = str(self.download_jobs.get(ids[0], {}).get("dest", ""))
            if path and os.path.exists(path):
                open_path(path)
    def _open_selected_folder(self) -> None:
        ids = self._selected_local_ids()
        if ids:
            path = str(self.download_jobs.get(ids[0], {}).get("dest", ""))
            if path:
                open_folder_for(path)
    def _copy_selected_path(self):
        ids=self._selected_local_ids();
        if ids:self.root.clipboard_clear();self.root.clipboard_append(str(self.download_jobs.get(ids[0],{}).get("dest","")))

    # ---------- Windows native .torrent drag/drop ----------
    def _enable_windows_file_drop(self) -> None:
        """Enable Explorer file drops without touching Tk from the native callback.

        Earlier builds called ``root.after`` directly from a subclassed Windows
        WndProc.  That is re-entrant into Tcl/Tk while Windows is still dispatching
        WM_DROPFILES and can terminate pythonw.exe, especially for multi-file drops.
        Here the WndProc does the minimum possible work: copy the file paths into a
        SimpleQueue and return.  A normal Tk ``after`` callback drains that queue.
        """
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()

            shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
            shell32.DragAcceptFiles.restype = None
            shell32.DragAcceptFiles(hwnd, True)

            WM_DROPFILES = 0x0233
            GWLP_WNDPROC = -4
            LRESULT = ctypes.c_ssize_t
            WPARAM_T = ctypes.c_size_t
            LPARAM_T = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM_T, LPARAM_T)

            getlong = user32.GetWindowLongPtrW
            setlong = user32.SetWindowLongPtrW
            call = user32.CallWindowProcW
            getlong.argtypes = [wintypes.HWND, ctypes.c_int]
            getlong.restype = ctypes.c_void_p
            setlong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            setlong.restype = ctypes.c_void_p
            call.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, WPARAM_T, LPARAM_T]
            call.restype = LRESULT

            HDROP = wintypes.HANDLE
            shell32.DragQueryFileW.argtypes = [HDROP, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
            shell32.DragQueryFileW.restype = wintypes.UINT
            shell32.DragFinish.argtypes = [HDROP]
            shell32.DragFinish.restype = None

            old = getlong(hwnd, GWLP_WNDPROC)
            if not old:
                raise OSError("Could not obtain the original Windows window procedure")

            def proc(h, m, w, l):
                if m == WM_DROPFILES:
                    paths: list[str] = []
                    hdrop = HDROP(w)
                    try:
                        count = int(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0))
                        # A corrupt/invalid HDROP should never make us allocate or loop
                        # an absurd number of entries.  Explorer drops are normally tiny.
                        if count < 0 or count > 4096:
                            return 0
                        for i in range(count):
                            n = int(shell32.DragQueryFileW(hdrop, i, None, 0))
                            if n <= 0 or n > 32767:
                                continue
                            buf = ctypes.create_unicode_buffer(n + 1)
                            copied = int(shell32.DragQueryFileW(hdrop, i, buf, n + 1))
                            if copied:
                                paths.append(buf.value)
                    except BaseException:
                        # Never let a Python exception unwind through a Win32 callback.
                        logging.exception("Failed to read WM_DROPFILES payload")
                    finally:
                        try:
                            shell32.DragFinish(hdrop)
                        except BaseException:
                            pass
                    if paths:
                        try:
                            self._native_drop_queue.put(tuple(paths))
                        except BaseException:
                            logging.exception("Failed to queue dropped paths")
                    return 0
                try:
                    return call(old, h, m, w, l)
                except BaseException:
                    # Returning zero is safer than unwinding through Windows.
                    logging.exception("CallWindowProcW failed")
                    return 0

            self._drop_proc = WNDPROC(proc)
            self._drop_old = old
            self._drop_hwnd = hwnd
            previous = setlong(hwnd, GWLP_WNDPROC, ctypes.cast(self._drop_proc, ctypes.c_void_p))
            if not previous:
                # SetWindowLongPtrW may legally return zero when the previous value is
                # zero, but WNDPROC should never be zero because we already read it.
                logging.warning("SetWindowLongPtrW returned NULL while installing drop hook")

            # Drain native drops only from Tk's normal event loop.
            self._native_drop_poll_after = self.root.after(75, self._poll_native_drop_queue)
            logging.info("Native Windows file drop enabled hwnd=%s", int(hwnd))
        except Exception:
            logging.exception("Native Windows drag/drop unavailable")

    def _poll_native_drop_queue(self) -> None:
        """Move copied Windows drop batches onto the normal Tk/UI thread."""
        try:
            merged: list[str] = []
            while True:
                try:
                    batch = self._native_drop_queue.get_nowait()
                except queue.Empty:
                    break
                merged.extend(batch)
            if merged:
                # Preserve Explorer's order and suppress exact duplicate paths from
                # one drag gesture without changing case/spelling for real files.
                unique = list(dict.fromkeys(merged))
                self._handle_dropped_paths(unique)
        except Exception:
            logging.exception("Failed while processing dropped torrent files")
            try:
                self.set_status("Could not process dropped torrent files. See rd-desktop.log.")
            except Exception:
                pass
        finally:
            try:
                if self.root.winfo_exists():
                    self._native_drop_poll_after = self.root.after(75, self._poll_native_drop_queue)
            except tk.TclError:
                self._native_drop_poll_after = None

    def _handle_dropped_paths(self, paths: list[str]) -> None:
        torrents = [p for p in paths if p.lower().endswith(".torrent") and Path(p).is_file()]
        if not torrents:
            self.set_status(self.t("drop_no_torrents"))
            return
        logging.info("Received %d dropped torrent file(s)", len(torrents))
        self._add_torrent_paths(torrents)

    def add_torrent_file(self) -> None:
        if self._show_existing_upload_queue():
            return
        paths = list(filedialog.askopenfilenames(
            title=self.t("choose_torrent_files"),
            filetypes=[(self.t("torrent_files_filter"), "*.torrent"), (self.t("all_files_filter"), "*.*")],
        ))
        if paths:
            self._add_torrent_paths(paths)

    def _add_torrent_paths(self, paths: list[str]) -> None:
        if self._show_existing_upload_queue():
            return
        if len(paths) == 1:
            path = paths[0]
            self.async_call(
                lambda: self._add_single_item_checked("torrent", path),
                self._after_single_item_checked,
                busy=self.t("uploading_torrent"),
            )
            return
        items = [{"kind": "torrent", "value": p, "label": self._queue_item_label(p, "torrent")} for p in paths]
        self._start_upload_queue(items)

    def _local_status_text(self,status:str)->str:
        mapping={"Queued":"status_queued","Cancelled":"status_cancelled","Downloading":"status_downloading","Completed":"status_completed","Missing":"status_missing","Paused":"status_paused","Failed":"status_failed"}
        return self.t(mapping[status]) if status in mapping else status

    def _close(self) -> None:
        self.closing = True
        self.download_stop.set()
        self.download_wakeup.set()
        with self.download_lock:
            controls = list(self.download_controls.items())
            for did, ctrl in controls:
                ctrl["action"] = "pause"
                ctrl["stop"].set()
                job = self.download_jobs.get(did)
                if job and job.get("status") == "Downloading":
                    job["status"] = "Paused"
                    self.local_status_state[did] = "Paused"
        self._save_download_jobs()
        try:
            if getattr(self, "_native_drop_poll_after", None):
                self.root.after_cancel(self._native_drop_poll_after)
                self._native_drop_poll_after = None
        except Exception:
            pass
        if os.name == "nt" and getattr(self, "_drop_old", None) and getattr(self, "_drop_hwnd", None):
            try:
                fn = ctypes.windll.user32.SetWindowLongPtrW
                fn.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                fn.restype = ctypes.c_void_p
                fn(self._drop_hwnd, -4, ctypes.c_void_p(self._drop_old))
            except Exception:
                pass
        self.root.destroy()


def run() -> int:
    root=tk.Tk()
    try:
        style=ttk.Style(root)
        if "vista" in style.theme_names():style.theme_use("vista")
    except Exception:pass
    RDModernApp(root);root.mainloop();return 0
