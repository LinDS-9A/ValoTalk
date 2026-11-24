"""截图时向外多扩几个像素，能看出窗口边缘有没有黑线。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

from PIL import ImageGrab

OUT = Path(__file__).resolve().parent.parent / "cache"
PAD = 6

with config_guard():
    from valotalk.app import App

    app = App()
    app._running = True
    for _ in range(28):
        app.root.update()
        time.sleep(0.07)
    app.root.update_idletasks()

    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    print(f"窗口 {x},{y} {w}x{h}")

    # 外扩 PAD，把窗口边框和桌面都拍进来
    img = ImageGrab.grab(bbox=(x - PAD, y - PAD, x + w + PAD, y + h + PAD))
    img.save(OUT / "shot_edge.png")
    print(f"存 cache/shot_edge.png  含外扩 {PAD}px（{img.width}x{img.height}）")

    # 顶部外扩的那几条带子单独放大
    topband = img.crop((0, 0, img.width, PAD * 3))
    topband = topband.resize((img.width, PAD * 3 * 4), 1)
    topband.save(OUT / "shot_topband.png")
    print(f"存 cache/shot_topband.png（顶部 {PAD*3}px 放大 4 倍）")

    app.shutdown()
