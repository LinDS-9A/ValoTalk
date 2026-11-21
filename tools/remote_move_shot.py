"""截图：手机遥控挪到功能开关区之后的面板。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App

OUT = Path(__file__).resolve().parent.parent / "cache"


def pump(app, n=16, gap=0.06):
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
pump(app, 22, 0.08)

# 关着的样子
shot(app.root, OUT / "ui_remote_off.png")

# 打开的样子
app.v_remote.set(True)
app._on_remote_toggle()
pump(app, 34, 0.06)
shot(app.root, OUT / "ui_remote_on.png")
print(f"  地址行: {app.remote_lbl.cget('text')}")

# 恢复关闭
app.v_remote.set(False)
app._on_remote_toggle()
pump(app, 12)

app.shutdown()