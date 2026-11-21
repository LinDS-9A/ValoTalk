"""截图：检查更新的三种结果弹窗。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App
from valotalk.update_ui import NoticeDialog, UpdateDialog
from valotalk import updater

OUT = Path(__file__).resolve().parent.parent / "cache"


def pump(app, n=14, gap=0.06):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


def shot(win, path, pad=12):
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

# 1) 已是最新
d1 = NoticeDialog(app.root, "已是最新版本",
                  f"当前版本 v2.1.3，没有可用的更新。", kind="ok")
pump(app, 10)
shot(d1.top, OUT / "update_latest.png")
d1.top.destroy()
pump(app, 4)

# 2) 检查失败
d2 = NoticeDialog(app.root, "检查更新失败",
                  "连不上更新服务器\n\n可能是网络问题，稍后再试。"
                  "也可以到 GitHub Releases 页面手动下载最新版。", kind="fail")
pump(app, 10)
shot(d2.top, OUT / "update_failed.png")
d2.top.destroy()
pump(app, 4)

# 3) 发现新版
info = updater.UpdateInfo(
    version="2.1.4",
    notes=("## 检查更新按钮\n"
           "- 面板顶部新增「检查更新」按钮\n"
           "- 已是最新时会明确告诉你\n\n"
           "## 其他\n"
           "- 自动检查依旧保留，两者互不干扰"))
d3 = UpdateDialog(app.root, info, app.updater,
                  on_applied=lambda: None, log=app.log,
                  on_later=lambda: None)
pump(app, 12)
shot(d3.top, OUT / "update_found.png")
d3.top.destroy()

app.shutdown()
print("\n三张截图完成")