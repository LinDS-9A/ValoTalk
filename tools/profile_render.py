"""找出渲染慢在哪。"""
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
    from valotalk.app import App

    t0 = time.time()
    app = App()
    app._running = True
    for _ in range(20):
        app.root.update()
        time.sleep(0.05)
    print(f"构建+首帧 {time.time()-t0:.2f}s\n")

    prof = cProfile.Profile()
    prof.enable()
    t0 = time.time()
    app._show_page("cfg")
    for _ in range(10):
        app.root.update()
        time.sleep(0.03)
    dt = time.time() - t0
    prof.disable()
    print(f"切到 cfg 用时 {dt:.2f}s\n")

    s = io.StringIO()
    ps = pstats.Stats(prof, stream=s).sort_stats("cumulative")
    ps.print_stats(18)
    out = s.getvalue()
    # 只打关键行
    for line in out.splitlines():
        if any(k in line for k in ("cumtime", "glass_over_bg", "bg_image",
                                   "_paint", "_redraw", "GaussianBlur",
                                   "_scaled_bg", "_repaint", "resize",
                                   "PhotoImage", "alpha_composite",
                                   "{built-in", "PIL")):
            print(line)

    app.shutdown()