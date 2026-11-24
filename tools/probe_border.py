"""试几种办法消除窗口那 7px 深色边框。

方案 A: DWMWA_BORDER_COLOR 设成浅灰（和界面同色）
方案 B: DWMWA_BORDER_COLOR 设成 NONE（透明）
方案 C: 去掉 WS_THICKFRAME（彻底没边框，但会失去拖拽调整大小）
每种都实测边框颜色变化。
"""
from __future__ import annotations
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

from PIL import ImageGrab

u = ctypes.WinDLL("user32", use_last_error=True)
dwm = ctypes.WinDLL("dwmapi")
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.GetWindowRect.restype = wintypes.BOOL
u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u.GetWindowLongW.restype = ctypes.c_long
u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
u.SetWindowLongW.restype = ctypes.c_long
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_uint]
u.SetWindowPos.restype = wintypes.BOOL

DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE
WS_THICKFRAME = 0x00040000
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


def border_color(hwnd):
    """取窗口最外圈 1px 的平均色。"""
    r = wintypes.RECT()
    if not u.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
        return None
    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
    a = np.array(img.convert("RGB"))
    top = a[0].mean(axis=0)
    left = a[:, 0].mean(axis=0)
    return tuple(int(x) for x in top), tuple(int(x) for x in left), \
        (r.right - r.left, r.bottom - r.top)


def set_border(hwnd, color_ref):
    v = ctypes.c_uint(color_ref)
    return dwm.DwmSetWindowAttribute(
        hwnd, DWMWA_BORDER_COLOR, ctypes.byref(v), ctypes.sizeof(v)) == 0


with config_guard():
    from valotalk.app import App
    from valotalk import winapi

    app = App()
    app._running = True
    for _ in range(24):
        app.root.update()
        time.sleep(0.07)
    app.root.update_idletasks()
    hwnd = winapi.top_level_hwnd(app.root)
    time.sleep(0.3)
    app.root.update()

    print("=" * 56)
    print("窗口边框现状")
    print("=" * 56)
    res = border_color(hwnd)
    print(f"  顶部边框色 {res[0]}   左边框色 {res[1]}   窗口尺寸 {res[2]}")

    print("\n[A] DWMWA_BORDER_COLOR = 浅灰 #DCDCE2")
    # COLORREF 是 0x00BBGGRR
    cr = 0x00E2DCDC
    print("    调用返回:", set_border(hwnd, cr))
    for _ in range(6):
        app.root.update()
        time.sleep(0.08)
    res = border_color(hwnd)
    print(f"    顶部 {res[0]}  左 {res[1]}")

    print("\n[B] DWMWA_BORDER_COLOR = NONE")
    print("    调用返回:", set_border(hwnd, DWMWA_COLOR_NONE))
    for _ in range(6):
        app.root.update()
        time.sleep(0.08)
    res = border_color(hwnd)
    print(f"    顶部 {res[0]}  左 {res[1]}")

    print("\n[C] 再调一次 SetWindowRgn（看 DWM 设置会不会被它冲掉）")
    scale = app.root.winfo_fpixels("1i") / 96.0
    winapi.round_window_region(hwnd, 22, scale)
    for _ in range(6):
        app.root.update()
        time.sleep(0.08)
    res = border_color(hwnd)
    print(f"    顶部 {res[0]}  左 {res[1]}")

    print("\n[D] 重新设边框色为浅灰（在 RGN 之后）")
    print("    调用返回:", set_border(hwnd, cr))
    for _ in range(6):
        app.root.update()
        time.sleep(0.08)
    res = border_color(hwnd)
    print(f"    顶部 {res[0]}  左 {res[1]}")

    print("\n[E] 去掉 WS_THICKFRAME（彻底没有 resize 边框）")
    style = u.GetWindowLongW(wintypes.HWND(hwnd), -16)
    print(f"    原 style {style:#x}")
    u.SetWindowLongW(wintypes.HWND(hwnd), -16,
                     ctypes.c_long(style & ~WS_THICKFRAME))
    u.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0), 0, 0, 0, 0,
                   SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                   | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    for _ in range(10):
        app.root.update()
        time.sleep(0.08)
    res = border_color(hwnd)
    print(f"    顶部 {res[0]}  左 {res[1]}  窗口尺寸 {res[2]}")
    print(f"    新 style {u.GetWindowLongW(wintypes.HWND(hwnd), -16):#x}")

    app.shutdown()
