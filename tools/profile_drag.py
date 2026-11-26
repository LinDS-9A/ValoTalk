"""模拟窗口拖动：测每次位置变化触发多少渲染开销。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

with config_guard():
    import valotalk.ui_theme as ui
    from valotalk.app import App

    # 统计渲染函数被调用多少次
    counts = {}

    def wrap(cls, name):
        orig = getattr(cls, name)

        def inner(*a, **kw):
            k = f"{cls.__name__}.{name}"
            counts[k] = counts.get(k, 0) + 1
            return orig(*a, **kw)

        setattr(cls, name, inner)

    for cls, names in (
        (ui.GradientPane, ("_paint",)),
        (ui.RoundCard, ("_redraw", "tint", "_tint_walk")),
    ):
        for n in names:
            if hasattr(cls, n):
                wrap(cls, n)

    t0 = time.time()
    app = App()
    app._running = True
    for _ in range(12):
        app.root.update()
    print(f"启动 {time.time()-t0:.1f}s")
    print(f"启动渲染调用: {counts}\n")

    # --- 模拟拖动：每次移动 8px，共 25 次 ---
    counts.clear()
    x0, y0 = app.root.winfo_rootx(), app.root.winfo_rooty()
    app.root.update_idletasks()

    t0 = time.time()
    for i in range(25):
        app.root.geometry(f"+{x0 + i*8}+{y0 + i*4}")
        app.root.update()
    dt = (time.time() - t0) * 1000
    n = len(app.root.winfo_toplevel().winfo_children())
    print(f"=== 模拟拖动 25 次（每次 8px）===  {dt:.0f}ms  "
          f"每次约 {dt/25:.1f}ms")
    print(f"  渲染调用: {counts}")
    total = sum(counts.values())
    print(f"  合计 {total} 次渲染 / 25 次位移 = {total/25:.1f} 次/次")

    # --- 对比：只改尺寸 ---
    counts.clear()
    t0 = time.time()
    for i in range(25):
        app.root.geometry(f"1024x{768 + i}")
        app.root.update()
    dt2 = (time.time() - t0) * 1000
    print(f"\n=== 模拟缩放 25 次 ===  {dt2:.0f}ms  每次约 {dt2/25:.1f}ms")
    print(f"  渲染调用: {counts}")

    app.shutdown()
