"""采样卡片玻璃的实际渲染色，作为卡片内控件的等效底色。"""
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
    for _ in range(28):
        app.root.update()
        time.sleep(0.07)
    app.root.update_idletasks()

    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    arr = np.array(ImageGrab.grab(bbox=(x, y, x + w, y + h)).convert("RGB"))
    print(f"窗口 {w}x{h}\n")

    def sample(name, wx, wy, ww, wh):
        """在控件区域内找出现最多的颜色（避开文字像素）。"""
        x0 = wx - x
        y0 = wy - y
        seg = arr[max(0, y0):y0 + wh, max(0, x0):x0 + ww]
        if seg.size == 0:
            print(f"  {name}: 区域无效")
            return None
        flat = seg.reshape(-1, 3)
        # 取每行中位数，避开文字
        med = np.median(flat, axis=0).astype(int)
        print(f"  {name:16s} 中位色 #{med[0]:02X}{med[1]:02X}{med[2]:02X}"
              f"  ({med[0]},{med[1]},{med[2]})")
        return med

    print("=== 卡片内各种区域的实际色 ===")
    # 日志卡
    lp = app.log_pane
    sample("日志卡（整块）", lp.winfo_rootx(), lp.winfo_rooty(),
           lp.winfo_width(), lp.winfo_height())
    sample("日志文字区", app.txt.winfo_rootx(), app.txt.winfo_rooty(),
           app.txt.winfo_width(), min(200, app.txt.winfo_height()))

    # 左列卡片
    for wdg, nm in ((app.left_pane, "left_pane"),):
        sample(nm, wdg.winfo_rootx(), wdg.winfo_rooty(),
               wdg.winfo_width(), min(120, wdg.winfo_height()))

    # head
    head = app._win_btns[0].master
    sample("head", head.winfo_rootx(), head.winfo_rooty(),
           head.winfo_width(), head.winfo_height())

    # dock
    d = app.dock
    sample("dock", d.winfo_rootx(), d.winfo_rooty(),
           d.winfo_width(), d.winfo_height())

    # 卡片圆角外的背景（作为对比）
    print("\n=== 对比：卡片外的壁纸色 ===")
    seg = arr[300, 0:14]
    print(f"  窗口最左缘 (x=0..14) 中位色 "
          f"#{int(np.median(seg[:,0])):02X}{int(np.median(seg[:,1])):02X}"
          f"{int(np.median(seg[:,2])):02X}")

    app.shutdown()