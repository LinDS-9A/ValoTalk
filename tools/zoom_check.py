"""放大检查：开关滑块 / 输入框 / dock 垫片 的圆角是否干净。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from _cfg_guard import config_guard

from PIL import ImageGrab

OUT = Path(__file__).resolve().parent.parent / "cache"


def corner_report(arr, name):
    """看四角是否残留白/灰方块：比较四角与中心的差距。"""
    h, w = arr.shape[:2]
    k = max(2, min(5, h // 6))
    tl = arr[0:k, 0:k].reshape(-1, 3).mean(axis=0)
    center = arr[h // 2, w // 2]
    print(f"  {name:12s} 左上角均色 {tuple(int(x) for x in tl)}  中心 {tuple(int(x) for x in center)}")


with config_guard():
    from valotalk.app import App
    import valotalk.ui_theme as ui

    app = App()
    app._running = True
    for _ in range(28):
        app.root.update()
        time.sleep(0.07)

    found = {"combo": [], "entry": [], "toggle": [], "dock": None}

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, ui.RoundCombo):
                found["combo"].append(c)
            elif isinstance(c, ui.RoundEntry):
                found["entry"].append(c)
            elif isinstance(c, ui.ToggleRow):
                found["toggle"].append(c)
            walk(c)

    walk(app.root)
    found["dock"] = getattr(app, "dock", None)

    def shot(widget, name, scale=4, pad=3):
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        w, h = widget.winfo_width(), widget.winfo_height()
        im = ImageGrab.grab(bbox=(x - pad, y - pad, x + w + pad, y + h + pad))
        im.resize((im.width * scale, im.height * scale), 1).save(
            OUT / f"zoom_{name}.png")
        arr = np.array(im.convert("RGB"))
        corner_report(arr, name)
        print(f"    → cache/zoom_{name}.png ({w}x{h} ×{scale})")

    if found["combo"]:
        shot(found["combo"][1], "combo")
    if found["entry"]:
        shot(found["entry"][0], "entry")
    if found["toggle"]:
        # 只拍开关本体
        shot(found["toggle"][0].switch, "toggle", scale=6)
    if found["dock"]:
        shot(found["dock"], "dock", scale=3)

    app.shutdown()
