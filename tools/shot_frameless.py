"""截无标题栏后的界面。"""
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
    for _ in range(30):
        app.root.update()
        time.sleep(0.07)

    for s in ("[识别] 云端 ASR 就绪",
              "队友：Rush B, plant the spike behind the box. → 冲B，在箱子后面下包。",
              "我：掩护我 → Cover me!",
              "聊天：gg wp → 打得好"):
        app.log(s)
    for _ in range(8):
        app.root.update()

    app.root.update_idletasks()
    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    print(f"窗口 {x},{y} {w}x{h}  frameless={app._frameless}")
    ImageGrab.grab(bbox=(x - 2, y - 2, x + w + 2, y + h + 2)).save(
        OUT / "shot_frameless.png")
    print("存 cache/shot_frameless.png")

    # 顶栏放大看窗口按钮
    hb = app._win_btns[0].master
    hb.update_idletasks()
    bx, by = hb.winfo_rootx(), hb.winfo_rooty()
    bw, bh = hb.winfo_width(), hb.winfo_height()
    im = ImageGrab.grab(bbox=(bx, by, bx + bw, by + bh))
    im.resize((bw * 2, bh * 2), 1).save(OUT / "shot_head.png")
    print(f"存 cache/shot_head.png ({bw}x{bh} 放大2倍)")

    app.shutdown()