"""
host/system_tray.py - Pure Win32 ctypes Windows Notification Area (System Tray) icon for TeamsStatus.

Provides a lightweight, zero-dependency system tray icon using Win32 Shell_NotifyIconW and GDI:
  - Dynamically renders a 32x32 ARGB circular status badge icon matching current Teams presence:
      * Green  : Available
      * Red    : InACall / InAMeeting / DoNotDisturb / Busy
      * Amber  : Away / BeRightBack
      * Gray   : Offline / NotRunning / Unknown
  - Displays live hover tooltip with current Teams status and RP2040 serial port state.
  - Opens a native popup menu on left-click or right-click with live status info and a
    "Stop TeamsMonitor" button that triggers graceful shutdown.
"""

import ctypes
from ctypes import wintypes
import sys
import threading
from typing import Callable, Dict, Optional, Tuple


# Win32 Constants
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_APP_UPDATE_TRAY = WM_USER + 21

WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_GRAYED = 0x00000001
MF_DISABLED = 0x00000002
MF_SEPARATOR = 0x00000800

TPM_LEFTALIGN = 0x0000
TPM_BOTTOMALIGN = 0x0020
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

IDI_APPLICATION = 32512
BI_RGB = 0
DIB_RGB_COLORS = 0

ID_TRAY_STOP = 1001

# Status RGB colors (R, G, B) for tray icon badge
STATUS_COLORS: Dict[str, Tuple[int, int, int]] = {
    "Available": (34, 197, 94),       # Green (#22C55E)
    "InACall": (239, 68, 68),         # Red (#EF4444)
    "InAMeeting": (239, 68, 68),      # Red (#EF4444)
    "DoNotDisturb": (239, 68, 68),    # Red (#EF4444)
    "Busy": (220, 38, 38),            # Crimson Red (#DC2626)
    "Away": (245, 158, 11),           # Amber (#F59E0B)
    "BeRightBack": (245, 158, 11),    # Amber (#F59E0B)
    "Offline": (100, 116, 139),       # Slate Gray (#64748B)
    "NotRunning": (100, 116, 139),    # Slate Gray (#64748B)
    "Unknown": (100, 116, 139),       # Slate Gray (#64748B)
}


if sys.platform == "win32":
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    gdi32 = ctypes.windll.gdi32

    LRESULT = wintypes.LPARAM
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uTimeoutOrVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    # Configure explicit 64-bit safe argtypes/restypes
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM

    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND

    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL

    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL

    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL

    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT

    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None

    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = wintypes.HMENU

    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL

    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.LPVOID,
    ]
    user32.TrackPopupMenu.restype = wintypes.BOOL

    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL

    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL

    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL

    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadIconW.restype = wintypes.HICON

    user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
    user32.CreateIconIndirect.restype = wintypes.HICON

    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL

    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT

    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(BITMAPINFOHEADER),
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP

    gdi32.CreateBitmap.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
    ]
    gdi32.CreateBitmap.restype = wintypes.HBITMAP

    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL


def _create_circle_hicon(r: int, g: int, b: int, size: int = 32) -> Optional[wintypes.HICON]:
    """
    Creates a 32x32 32-bit ARGB circular badge HICON in memory using Win32 GDI.
    Draws a smooth anti-aliased circle with a subtle dark outer border and inner highlight.
    """
    if sys.platform != "win32":
        return None

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = size
    bmi.biHeight = -size  # Top-down DIB
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = BI_RGB

    ppv_bits = ctypes.c_void_p()
    hbm_color = gdi32.CreateDIBSection(None, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(ppv_bits), None, 0)
    if not hbm_color or not ppv_bits.value:
        return None

    # Build 32-bit BGRA pixel buffer (premultiplied alpha)
    pixel_array_type = ctypes.c_uint32 * (size * size)
    pixels = pixel_array_type.from_address(ppv_bits.value)

    center = (size - 1) / 2.0
    outer_radius = (size / 2.0) - 1.5
    inner_radius = outer_radius - 2.2

    for y in range(size):
        for x in range(size):
            dx = x - center
            dy = y - center
            dist = (dx * dx + dy * dy) ** 0.5

            if dist > outer_radius + 0.7:
                # Fully transparent outside circle
                pixels[y * size + x] = 0x00000000
            else:
                # Smooth edge alpha
                if dist > outer_radius - 0.5:
                    alpha_f = max(0.0, min(1.0, (outer_radius + 0.7 - dist) / 1.2))
                else:
                    alpha_f = 1.0

                if dist > inner_radius:
                    # Dark outer ring (#1E293B)
                    pr, pg, pb = 30, 41, 59
                else:
                    # Slight top-left specular highlight for crisp badge look
                    highlight = max(0.0, (center - x) * 0.015 + (center - y) * 0.02)
                    pr = min(255, int(r + (255 - r) * highlight))
                    pg = min(255, int(g + (255 - g) * highlight))
                    pb = min(255, int(b + (255 - b) * highlight))

                a = int(alpha_f * 255)
                pr = int(pr * alpha_f)
                pg = int(pg * alpha_f)
                pb = int(pb * alpha_f)

                pixels[y * size + x] = (a << 24) | (pr << 16) | (pg << 8) | pb

    # Create 1-bpp mask bitmap
    mask_bytes = ((size + 15) // 16) * 2 * size
    mask_buf = (ctypes.c_ubyte * mask_bytes)()
    hbm_mask = gdi32.CreateBitmap(size, size, 1, 1, ctypes.byref(mask_buf))

    icon_info = ICONINFO()
    icon_info.fIcon = True
    icon_info.xHotspot = 0
    icon_info.yHotspot = 0
    icon_info.hbmMask = hbm_mask
    icon_info.hbmColor = hbm_color

    hicon = user32.CreateIconIndirect(ctypes.byref(icon_info))

    if hbm_mask:
        gdi32.DeleteObject(hbm_mask)
    if hbm_color:
        gdi32.DeleteObject(hbm_color)

    return hicon


class SystemTrayIcon:
    """
    Manages a Windows Notification Area (System Tray) icon in a background daemon thread.
    """

    def __init__(self, on_stop: Callable[[], None]):
        self.on_stop = on_stop
        self._lock = threading.Lock()
        self._status = "Unknown"
        self._port: Optional[str] = None
        self._hwnd: Optional[wintypes.HWND] = None
        self._nid: Optional[NOTIFYICONDATAW] = None
        self._icon_cache: Dict[Tuple[int, int, int], wintypes.HICON] = {}
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._wndproc_ref = None
        self._taskbar_created_msg = 0

    def start(self) -> None:
        """Starts the system tray icon message loop on a background daemon thread."""
        if sys.platform != "win32":
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_message_loop, name="TeamsStatusTrayThread", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def update_state(self, status: Optional[str] = None, port: Optional[str] = None) -> None:
        """Updates the tray icon color and tooltip text to reflect current status and serial port."""
        if sys.platform != "win32":
            return
        with self._lock:
            if status is not None:
                self._status = status
            self._port = port
            hwnd = self._hwnd
        if hwnd:
            user32.PostMessageW(hwnd, WM_APP_UPDATE_TRAY, 0, 0)

    def stop(self) -> None:
        """Removes the tray icon from the Windows notification area and stops the message loop."""
        if sys.platform != "win32":
            return
        with self._lock:
            hwnd = self._hwnd
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)

    def _get_or_create_icon(self, status: str) -> wintypes.HICON:
        rgb = STATUS_COLORS.get(status, STATUS_COLORS["Unknown"])
        if rgb not in self._icon_cache:
            hicon = _create_circle_hicon(*rgb)
            if not hicon:
                hicon = user32.LoadIconW(None, ctypes.cast(IDI_APPLICATION, wintypes.LPCWSTR))
            self._icon_cache[rgb] = hicon
        return self._icon_cache[rgb]

    def _build_tooltip(self, status: str, port: Optional[str]) -> str:
        port_label = f"RP2040 on {port}" if port else "Waiting for RP2040..."
        on_air_States = ("InACall", "InAMeeting", "DoNotDisturb")
        air_label = " [ON AIR]" if status in on_air_States else (" [PULSE]" if status == "Busy" else "")
        tip = f"TeamsStatus: {status}{air_label} ({port_label})"
        return tip[:127]

    def _refresh_notify_icon(self, modify: bool = True) -> None:
        with self._lock:
            status = self._status
            port = self._port
            hwnd = self._hwnd
            nid = self._nid

        if not hwnd or not nid:
            return

        nid.hIcon = self._get_or_create_icon(status)
        nid.szTip = self._build_tooltip(status, port)
        shell32.Shell_NotifyIconW(NIM_MODIFY if modify else NIM_ADD, ctypes.byref(nid))

    def _show_context_menu(self, hwnd: wintypes.HWND) -> None:
        with self._lock:
            status = self._status
            port = self._port

        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            return

        try:
            port_text = f"RP2040: Connected ({port})" if port else "RP2040: Disconnected (Auto-Scanning)"
            user32.AppendMenuW(hmenu, MF_STRING | MF_GRAYED | MF_DISABLED, 0, "TeamsStatus Monitor")
            user32.AppendMenuW(hmenu, MF_STRING | MF_GRAYED | MF_DISABLED, 0, f"Status: {status}")
            user32.AppendMenuW(hmenu, MF_STRING | MF_GRAYED | MF_DISABLED, 0, port_text)
            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(hmenu, MF_STRING, ID_TRAY_STOP, "Stop TeamsMonitor")

            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))

            # Required by Win32 so the popup menu dismisses properly when clicking outside
            user32.SetForegroundWindow(hwnd)
            cmd = user32.TrackPopupMenu(
                hmenu,
                TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                pt.x,
                pt.y,
                0,
                hwnd,
                None,
            )
            user32.PostMessageW(hwnd, 0, 0, 0)

            if cmd == ID_TRAY_STOP:
                # Remove icon immediately for snappy user feedback, then invoke stop callback
                if self._nid:
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                try:
                    self.on_stop()
                finally:
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        finally:
            user32.DestroyMenu(hmenu)

    def _run_message_loop(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = f"TeamsStatusTrayWnd_{id(self)}"
        self._taskbar_created_msg = user32.RegisterWindowMessageW("TaskbarCreated")

        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAYICON:
                event = lparam & 0xFFFF
                if event in (WM_RBUTTONUP, WM_LBUTTONUP, WM_CONTEXTMENU):
                    self._show_context_menu(hwnd)
                return 0
            elif msg == WM_APP_UPDATE_TRAY:
                self._refresh_notify_icon(modify=True)
                return 0
            elif self._taskbar_created_msg and msg == self._taskbar_created_msg:
                # Re-add tray icon if Windows Explorer restarts
                self._refresh_notify_icon(modify=False)
                return 0
            elif msg == WM_CLOSE:
                if self._nid:
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                user32.DestroyWindow(hwnd)
                return 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(_wnd_proc)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinstance
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = class_name
        wc.hIconSm = None

        user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "TeamsStatusMonitorTray",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )

        if not hwnd:
            self._ready.set()
            return

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON

        with self._lock:
            self._hwnd = hwnd
            self._nid = nid

        self._refresh_notify_icon(modify=False)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup cached HICON handles
        for hicon in self._icon_cache.values():
            if hicon:
                user32.DestroyIcon(hicon)
        self._icon_cache.clear()

        with self._lock:
            self._hwnd = None
            self._nid = None
