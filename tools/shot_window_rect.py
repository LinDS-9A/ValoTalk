"""按「窗口矩形」截图（含边框），这是用户实际看到的样子。

winfo_rootx/rooty 给的是客户区坐标，会把边框切掉；
这里用 Win32 GetWindowRect 拿带边框的完整矩形。
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

OUT = Path(__file__).resolve().parent.parent / "cache"


def window_rect(hwnd):
    r = wintypes.RECT()
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetWindowRect.restype = wintypes.BOOL
    if not u.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


with config_guard():
    from valotalk.app import App
    from valotalk import winapi

    app = App()
    app._running = True
    for _ in range(28):
        app.root.update()
        time.sleep(0.07)
    app.root.update_idletasks()

    hwnd = winapi.top_level_hwnd(app.root)
    wr = window_rect(hwnd)
    cx, cy = app.root.winfo_rootx(), app.root.winfo_rooty()
    cw, ch = app.root.winfo_width(), app.root.winfo_height()
    print(f"客户区  ({cx},{cy}) {cw}x{ch}")
    print(f"窗口矩形 {wr}  尺寸 {wr[2]-wr[0]}x{wr[3]-wr[1]}")
    dx = cx - wr[0]
    dy = cy - wr[1]
    print(f"边框厚度 左/上 = {dx}, {dy}  "
          f"右 = {wr[2] - (cx+cw)}, 下 = {wr[3] - (cy+ch)}")

    img = ImageGrab.grab(bbox=(wr[0], wr[1], wr[2], wr[3]))
    img.save(OUT / "shot_fullwindow.png")
    print(f"\n存 cache/shot_fullwindow.png  {img.width}x{img.height}（含边框）")

    arr = np.array(img.convert("RGB"))
    print("\n最外圈像素（如果边框透明应该和界面同色，不该是黑的）:")
    for r in range(min(3, arr.shape[0])):
        row = arr[r]
        print(f"  上边第{r}行  均值{row.mean():6.1f}  最暗{row.min():3d}  "
              f"中位#{int(np.median(row[:,0])):02X}"
              f"{int(np.median(row[:,1])):02X}{int(np.median(row[:,2])):02X}")
    for c in range(min(3, arr.shape[1])):
        col = arr[:, c]
        print(f"  左边第{c}列  均值{col.mean():6.1f}  最暗{col.min():3d}")

    # 顶部那条带子放大
    band = img.crop((0, 0, img.width, max(8, dy + 4)))
    band = band.resize((img.width, band.height * 5), 1)
    band.save(OUT / "shot_topedge.png")
    print(f"\n存 cache/shot_topedge.png（顶部 {band.height//5}px 放大 5 倍）")

    app.shutdown()
