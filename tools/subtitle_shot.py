"""截图：字幕调节控件 + 不同字号的实际显示。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App

OUT = Path(__file__).resolve().parent.parent / "cache"


def pump(app, n=12, gap=0.05):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


def shot(win, path, pad=10):
    import mss
    import numpy as np
    from PIL import Image
    factory = getattr(mss, "MSS", None) or mss.mss
    win.update_idletasks()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    with factory() as sct:
        g = sct.grab({"left": x - pad, "top": y - pad,
                      "width": w + pad * 2, "height": h + pad * 2})
        arr = np.asarray(g)[:, :, :3][:, :, ::-1]
    Image.fromarray(arr).save(path)
    print(f"  {path.name}  ({w}x{h})")


app = App()
app._running = True
pump(app, 18, 0.08)

# 主面板（含字幕调节行）
app.log("[字幕] 字号 19 → 20")
pump(app, 4)
shot(app.root, OUT / "ui_subtitle_ctl.png")

# 不同字号的字幕窗
ov = app.overlay
for size, name in ((14, "sub_small"), (19, "sub_mid"), (30, "sub_big")):
    ov.set_font_size(size, save=False)
    ov.clear()
    pump(app, 3)
    ov.items.clear()
    ov._add_main("队友", "Enemy one tap on A site, watch the flank.",
                 "敌人在包点一枪头，注意绕后", 60)
    ov._add_main("我", "Cover me, I'm ulting!",
                 "掩护我，我要开大了", 60)
    pump(app, 5)
    shot(ov.win, OUT / f"{name}.png", pad=8)

ov.set_font_size(19, save=False)
ov.clear()
app.shutdown()