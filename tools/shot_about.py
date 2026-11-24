"""截关于页（含赞助码）。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

from PIL import ImageGrab

OUT = Path(__file__).resolve().parent.parent / "cache"

with config_guard():
    from valotalk.app import App

    app = App()
    app._running = True
    for _ in range(28):
        app.root.update()
        time.sleep(0.07)

    app._show_page("about")
    for _ in range(18):
        app.root.update()
        time.sleep(0.06)
    app.root.update_idletasks()

    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(OUT / "shot_about.png")
    print(f"存 cache/shot_about.png ({w}x{h})")

    # 滚动到底再看一眼赞助区
    cv = app._page_canvas
    cv.yview_moveto(1.0)
    for _ in range(12):
        app.root.update()
        time.sleep(0.05)
    for _ in range(10):
        app.root.update()
        time.sleep(0.05)
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(OUT / "shot_about_bottom.png")
    print("存 cache/shot_about_bottom.png")

    app.shutdown()