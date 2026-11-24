"""定位 frameless_test 卡在哪一步（每步都打时间戳）。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard


def step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


with config_guard():
    step("导入 App")
    from valotalk.app import App

    step("构造 App")
    t0 = time.time()
    app = App()
    app._running = True
    step(f"构造完成 {time.time()-t0:.2f}s")

    step("跑 20 帧")
    for i in range(20):
        app.root.update()
        time.sleep(0.05)
    step("帧跑完")

    step("读 three win_btns")
    btns = getattr(app, "_win_btns", [])
    step(f"按钮 {[b._kind for b in btns]}")

    step("测拖动：生成 Button-1")
    head = btns[0].master
    x0, y0 = app.root.winfo_x(), app.root.winfo_y()
    head.event_generate("<Button-1>", x=5, y=5, rootx=x0 + 5, rooty=y0 + 5)
    step(f"生成完，_drag_off={app._drag_off}")

    step("跑 3 帧")
    for _ in range(3):
        app.root.update()
        time.sleep(0.05)
    step("回来了")

    step("测拖动：B1-Motion")
    head.event_generate("<B1-Motion>", x=5, y=5, rootx=x0 + 65, rooty=y0 + 45)
    step("Motion 生成完")

    step("跑 3 帧")
    for _ in range(3):
        app.root.update()
        time.sleep(0.05)
    step(f"位置 ({app.root.winfo_x()},{app.root.winfo_y()})")

    step("测最大化")
    app._toggle_maximize()
    step("调用返回")
    for _ in range(10):
        app.root.update()
        time.sleep(0.05)
    step(f"最大化后 {app.root.geometry()}")

    step("还原")
    app._toggle_maximize()
    for _ in range(10):
        app.root.update()
        time.sleep(0.05)
    step(f"还原后 {app.root.geometry()}")

    step("切页")
    for p in ("cfg", "about", "home"):
        app._show_page(p)
        for _ in range(5):
            app.root.update()
            time.sleep(0.03)
    step("切页完成")

    step("关闭")
    app.shutdown()
    step("结束")