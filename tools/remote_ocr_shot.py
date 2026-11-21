"""截图：手机开关 + OCR 速度档位。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App

OUT = Path(__file__).resolve().parent.parent / "cache"


def pump(app, n=14, gap=0.06):
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
pump(app, 20, 0.08)

app.log("[手机] 遥控已开启：10.223.71.236:8765")
app.log("[OCR] 线程 1 → 2（平衡（650ms））：CPU 和速度折中")
pump(app, 6)
shot(app.root, OUT / "ui_remote_ocr.png")

# 量关键区域
RX, RY = app.root.winfo_rootx(), app.root.winfo_rooty()
RH = app.root.winfo_height()


def rel(w):
    return (w.winfo_rootx() - RX, w.winfo_rooty() - RY,
            w.winfo_width(), w.winfo_height())


print("\n右列各卡片高度：")
for name, wd in (("快捷键", app.btn_remote.master.master),
                 ("聊天翻译", app.cb_ocr_speed.master.master),
                 ("日志", app.txt.master.master)):
    x, y, w, h = rel(wd)
    print(f"  {name:8s} y={y:3d} h={h:3d}  底部={y+h}")

print(f"\n日志文本框高 {app.txt.winfo_height()}px")
print(f"窗口高 {RH}px")

app.shutdown()