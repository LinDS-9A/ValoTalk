"""定位顶部黑线：采样窗口最上沿几行。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

from PIL import ImageGrab

with config_guard():
    from valotalk.app import App

    app = App()
    app._running = True
    for _ in range(26):
        app.root.update()
        time.sleep(0.06)
    app.root.update_idletasks()

    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    print(f"窗口 {x},{y} {w}x{h}")

    arr = np.array(ImageGrab.grab(bbox=(x, y, x + w, y + 16)).convert("RGB"))
    print("\n顶部 16 行：")
    for r in range(min(10, arr.shape[0])):
        row = arr[r]
        med = np.median(row, axis=0).astype(int)
        print(f"  第{r:2d}行  中位 #{med[0]:02X}{med[1]:02X}{med[2]:02X}  "
              f"最暗 {row.min():3d}  最亮 {row.max():3d}")

    # 左边缘
    arr2 = np.array(ImageGrab.grab(bbox=(x, y, x + 14, y + h)).convert("RGB"))
    print("\n左边缘 8 列：")
    for c in range(min(6, arr2.shape[1])):
        col = arr2[:, c]
        med = np.median(col, axis=0).astype(int)
        print(f"  第{c:2d}列  中位 #{med[0]:02X}{med[1]:02X}{med[2]:02X}  "
              f"最暗 {col.min():3d}")

    app.shutdown()
