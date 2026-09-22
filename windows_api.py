from __future__ import annotations

import ctypes
import os
import threading
from dataclasses import dataclass
from ctypes import wintypes
from typing import Callable, Iterable

import numpy as np


if os.name != "nt":
    raise RuntimeError("本程序仅支持 Windows。")


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


@dataclass(frozen=True, slots=True)
class Bounds:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True, slots=True)
class ClientCapture:
    """目标客户区截图及其到物理客户区坐标的缩放关系。"""

    image: np.ndarray
    scale_x: float
    scale_y: float


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL

try:
    _get_window_dpi_awareness_context = user32.GetWindowDpiAwarenessContext
    _get_window_dpi_awareness_context.argtypes = [wintypes.HWND]
    _get_window_dpi_awareness_context.restype = wintypes.HANDLE
    _set_thread_dpi_awareness_context = user32.SetThreadDpiAwarenessContext
    _set_thread_dpi_awareness_context.argtypes = [wintypes.HANDLE]
    _set_thread_dpi_awareness_context.restype = wintypes.HANDLE
except AttributeError:
    _get_window_dpi_awareness_context = None
    _set_thread_dpi_awareness_context = None

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int


GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
GA_ROOT = 2

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
HWND_TOP = wintypes.HWND(0)

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0


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


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", ctypes.c_ubyte),
        ("rgbGreen", ctypes.c_ubyte),
        ("rgbRed", ctypes.c_ubyte),
        ("rgbReserved", ctypes.c_ubyte),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


def set_per_monitor_dpi_awareness() -> None:
    """启用 Per-Monitor V2，保证截图和叠加层使用同一物理像素坐标。"""

    try:
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [wintypes.HANDLE]
        set_context.restype = wintypes.BOOL
        set_context(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


def get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def find_target_window(keywords: Iterable[str]) -> int | None:
    lowered = tuple(keyword.casefold() for keyword in keywords if keyword)
    candidates: list[tuple[int, int]] = []

    @WNDENUMPROC
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        title = get_window_title(hwnd)
        if not title or not any(keyword in title.casefold() for keyword in lowered):
            return True
        bounds = get_client_bounds(hwnd)
        if bounds is not None and bounds.width >= 300 and bounds.height >= 200:
            candidates.append((bounds.width * bounds.height, int(hwnd)))
        return True

    user32.EnumWindows(callback, 0)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def get_client_bounds(hwnd: int) -> Bounds | None:
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    top_left = wintypes.POINT(rect.left, rect.top)
    bottom_right = wintypes.POINT(rect.right, rect.bottom)
    if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        return None
    if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
        return None
    width = int(bottom_right.x - top_left.x)
    height = int(bottom_right.y - top_left.y)
    if width <= 0 or height <= 0:
        return None
    return Bounds(int(top_left.x), int(top_left.y), width, height)


def virtual_screen_bounds() -> Bounds:
    return Bounds(
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def intersect_bounds(first: Bounds, second: Bounds) -> Bounds | None:
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.right, second.right)
    bottom = min(first.bottom, second.bottom)
    if right <= left or bottom <= top:
        return None
    return Bounds(left, top, right - left, bottom - top)


def target_is_active(target_hwnd: int) -> bool:
    foreground = int(user32.GetForegroundWindow() or 0)
    if foreground == 0:
        return False
    return get_window_pid(foreground) == get_window_pid(target_hwnd)


def get_toplevel_hwnd(widget_hwnd: int) -> int:
    """将 TkChild 句柄解析为真正承载窗口样式和屏幕坐标的 TkTopLevel。"""

    root_hwnd = int(user32.GetAncestor(widget_hwnd, GA_ROOT) or 0)
    if root_hwnd == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    return root_hwnd


def calculate_capture_scale(
    physical_width: int,
    physical_height: int,
    capture_width: int,
    capture_height: int,
) -> tuple[float, float]:
    """计算 PrintWindow 逻辑像素到叠加层物理像素的转换比例。"""

    if min(physical_width, physical_height, capture_width, capture_height) <= 0:
        raise ValueError("客户区与截图尺寸必须大于 0")
    return physical_width / capture_width, physical_height / capture_height


def capture_client_frame(hwnd: int) -> ClientCapture | None:
    """使用目标窗口自身 DPI 上下文截图，并返回到物理客户区的缩放比例。"""

    bounds = get_client_bounds(hwnd)
    if bounds is None or bounds.width <= 0 or bounds.height <= 0:
        return None

    previous_dpi_context = None
    if _get_window_dpi_awareness_context is not None and _set_thread_dpi_awareness_context is not None:
        target_context = _get_window_dpi_awareness_context(hwnd)
        if target_context:
            previous_dpi_context = _set_thread_dpi_awareness_context(target_context)

    try:
        logical_rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(logical_rect)):
            return None
        capture_width = int(logical_rect.right - logical_rect.left)
        capture_height = int(logical_rect.bottom - logical_rect.top)
        if capture_width <= 0 or capture_height <= 0:
            return None

        source_dc = user32.GetDC(hwnd)
        if not source_dc:
            return None
        memory_dc = gdi32.CreateCompatibleDC(source_dc)
        bitmap = gdi32.CreateCompatibleBitmap(source_dc, capture_width, capture_height)
        if not memory_dc or not bitmap:
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(hwnd, source_dc)
            return None
        previous_object = gdi32.SelectObject(memory_dc, bitmap)
        try:
            if not user32.PrintWindow(hwnd, memory_dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
                return None
            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = capture_width
            info.bmiHeader.biHeight = -capture_height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB
            buffer = (ctypes.c_ubyte * (capture_width * capture_height * 4))()
            copied = gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                capture_height,
                ctypes.byref(buffer),
                ctypes.byref(info),
                DIB_RGB_COLORS,
            )
            if copied != capture_height:
                return None
            image = np.frombuffer(buffer, dtype=np.uint8).reshape((capture_height, capture_width, 4))
            bgr = image[:, :, :3].copy()
            if float(bgr.std()) < 1.0:
                return None
            scale_x, scale_y = calculate_capture_scale(
                bounds.width,
                bounds.height,
                capture_width,
                capture_height,
            )
            return ClientCapture(bgr, scale_x, scale_y)
        finally:
            if previous_object:
                gdi32.SelectObject(memory_dc, previous_object)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(hwnd, source_dc)
    finally:
        if previous_dpi_context and _set_thread_dpi_awareness_context is not None:
            _set_thread_dpi_awareness_context(previous_dpi_context)


def capture_client_image(hwnd: int) -> np.ndarray | None:
    """兼容旧调用，只返回目标客户区的原始逻辑像素图像。"""

    capture = capture_client_frame(hwnd)
    return capture.image if capture is not None else None


def _set_window_long_ptr(hwnd: int, index: int, value: int) -> None:
    ctypes.set_last_error(0)
    previous = int(user32.SetWindowLongPtrW(hwnd, index, value))
    error = ctypes.get_last_error()
    if previous == 0 and error:
        raise ctypes.WinError(error)


def configure_overlay_window(overlay_hwnd: int, owner_hwnd: int) -> None:
    ex_style = int(user32.GetWindowLongPtrW(overlay_hwnd, GWL_EXSTYLE))
    ex_style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    ex_style &= ~WS_EX_TOPMOST
    _set_window_long_ptr(overlay_hwnd, GWL_EXSTYLE, ex_style)
    _set_window_long_ptr(overlay_hwnd, GWLP_HWNDPARENT, owner_hwnd)
    if not user32.SetWindowPos(
        overlay_hwnd,
        HWND_TOP,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def position_overlay(overlay_hwnd: int, bounds: Bounds) -> None:
    if not user32.SetWindowPos(
        overlay_hwnd,
        HWND_TOP,
        bounds.left,
        bounds.top,
        bounds.width,
        bounds.height,
        SWP_NOACTIVATE | SWP_SHOWWINDOW,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


class HotkeyListener:
    """在独立消息线程中监听全局快捷键。"""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="overlay-hotkeys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self) -> None:
        self._thread_id = int(kernel32.GetCurrentThreadId())
        bindings = {
            1: (ord("G"), "toggle"),
            2: (ord("Q"), "quit"),
            3: (ord("D"), "debug"),
        }
        registered: list[int] = []
        for hotkey_id, (key_code, _command) in bindings.items():
            if user32.RegisterHotKey(None, hotkey_id, MOD_CONTROL | MOD_ALT, key_code):
                registered.append(hotkey_id)
        try:
            message = wintypes.MSG()
            while True:
                result = int(user32.GetMessageW(ctypes.byref(message), None, 0, 0))
                if result <= 0:
                    break
                if message.message == WM_HOTKEY:
                    binding = bindings.get(int(message.wParam))
                    if binding is not None:
                        self._callback(binding[1])
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)

