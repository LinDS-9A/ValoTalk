"""截手机遥控二维码窗口，确认真的能看到图。"""
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

    if not app.remote.url:
        app.chk_remote.var.set(True)
        try:
            app._on_remote_toggle()
        except Exception:
            pass
        for _ in range(30):
            app.root.update()
            time.sleep(0.08)

    print("地址:", app.remote.url)
    app._show_remote_qr()
    for _ in range(16):
        app.root.update()
        time.sleep(0.07)

    tops = [w for w in app.root.winfo_children()
            if w.winfo_class() == "Toplevel" and w.title() == "手机遥控"]
    if not tops:
        print("没弹出窗口")
        app.shutdown()
        raise SystemExit(1)

    t = tops[0]
    t.update_idletasks()
    x, y = t.winfo_rootx(), t.winfo_rooty()
    w, h = t.winfo_width(), t.winfo_height()
    print(f"窗口 ({x},{y}) {w}x{h}")
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(OUT / "shot_qr.png")
    print("存 cache/shot_qr.png")

    import numpy as np
    arr = np.array(img.convert("RGB"))
    # 二维码是黑白格：统计纯黑像素比例，太低说明是白板
    dark = int((arr.mean(axis=2) < 60).sum())
    print(f"  纯黑像素 {dark} 个（{dark / (arr.shape[0] * arr.shape[1]) * 100:.1f}%）")
    print("  二维码画出来了吗:", "是" if dark > 2000 else "否（可能空白）")

    app.shutdown()
