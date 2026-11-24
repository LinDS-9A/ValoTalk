"""profile 简约档的窗口缩放，看还剩什么在花时间。"""
from __future__ import annotations
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

with config_guard():
    import valotalk.ui_theme as ui
    from valotalk.app import App

    ui.set_mode("lite")
    app = App()
    app._running = True
    for _ in range(14):
        app.root.update()

    prof = cProfile.Profile()
    prof.enable()
    t0 = time.time()
    app.root.geometry("1000x700")
    for _ in range(10):
        app.root.update()
    dt = time.time() - t0
    prof.disable()
    print(f"缩放耗时 {dt*1000:.0f} ms")

    s = io.StringIO()
    pstats.Stats(prof, stream=s).sort_stats("cumulative").print_stats(20)
    keys = ("cumtime", "round_image", "glass_over_bg", "_paint", "_redraw",
            "tint", "_tint_walk", "configure", "_sync_height", "resize",
            "PhotoImage", "_lock_aspect", "geometry", "update_idletasks",
            "_eq_for", "flat_layers")
    for line in s.getvalue().splitlines():
        if any(k in line for k in keys):
            print(line)

    app.shutdown()
