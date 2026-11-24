"""像素级验证：内容确实顶到窗口最上沿（没有系统标题栏占位）。

⚠️ 不断言「顶部颜色是深色」—— 背景图是插画压暗，颜色取决于图；
真正要证明的是**布局**：head 和窗口按钮都贴在窗口顶部。
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

from PIL import ImageGrab

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


with config_guard():
    from valotalk.app import App

    app = App()
    app._running = True
    for _ in range(30):
        app.root.update()
        time.sleep(0.07)
    app.root.update_idletasks()

    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    print(f"窗口 {x},{y} {w}x{h}  frameless={app._frameless}\n")

    head = app._win_btns[0].master
    head_y = head.winfo_rooty() - y
    print(f"head 相对窗口 y={head_y}")

    print("=== 1) 布局：内容顶到上沿 ===")
    check("head 在窗口顶部 60px 内", head_y < 60, f"y={head_y}")

    print("\n=== 2) 窗口按钮贴顶 ===")
    for b in app._win_btns:
        bx = b.winfo_rootx() - x
        by = b.winfo_rooty() - y
        bw = b.winfo_width()
        print(f"  {b._kind:6s} x={bx:4d} y={by:3d} w={bw}")
        check(f"{b._kind} 在顶部 60px 内", by < 60, f"y={by}")
    # 关闭键必须最靠右
    rights = {b._kind: (b.winfo_rootx() - x) for b in app._win_btns}
    print(f"  横向位置: {rights}")
    check("关闭键在最右", rights["close"] == max(rights.values()), str(rights))

    print("\n=== 3) 顶部可见区域是界面（有明暗变化）===")
    arr = np.array(ImageGrab.grab(bbox=(x, y, x + w, y + min(80, h)))
                   .convert("RGB"))
    print(f"  截取前 80 行，形状 {arr.shape}")
    # 界面顶部有文字和按钮，横向必然有明暗变化；系统标题栏很平
    row_std = arr[30].std() if arr.shape[0] > 30 else arr[0].std()
    print(f"  第 30 行横向标准差 = {row_std:.1f}")
    check("顶部横向有内容变化（不是一条平色栏）", row_std > 8,
          f"std={row_std:.1f}")

    print("\n=== 4) 窗口底部 dock 完整 ===")
    d = app.dock
    dy = d.winfo_rooty() - y
    dh = d.winfo_height()
    print(f"  dock y={dy} h={dh} 底边={dy + dh} / 窗口高 {h}")
    check("dock 底边在窗口内", dy + dh <= h, f"{dy + dh} > {h}")
    check("dock 没被裁（高 54）", dh >= 50, str(dh))

    print("\n=== 5) 最大化后依然无标题栏 ===")
    app._toggle_maximize()
    for _ in range(24):
        app.root.update()
        time.sleep(0.05)
    app.root.update_idletasks()
    x2, y2 = app.root.winfo_rootx(), app.root.winfo_rooty()
    hy2 = head.winfo_rooty() - y2
    b2 = app._win_btns[0]
    by2 = b2.winfo_rooty() - y2
    print(f"  最大化 {app.root.winfo_width()}x{app.root.winfo_height()}")
    print(f"  head y={hy2}  关闭键 y={by2}")
    check("最大化后 head 仍贴顶", hy2 < 60, f"y={hy2}")
    check("最大化后按钮仍在顶部", by2 < 60, f"y={by2}")

    app._toggle_maximize()
    for _ in range(20):
        app.root.update()
        time.sleep(0.05)

    app.shutdown()

print("\n" + "=" * 52)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 52)
sys.exit(0 if failed == 0 else 1)