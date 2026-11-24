"""干净对比：只计我们自己的渲染函数耗时，不含 Tk 布局。"""
from __future__ import annotations
import cProfile
import io as _io
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard


def measure(mode: str):
    import valotalk.ui_theme as ui

    # 必须写进配置：App.__init__ 会按 ui.render_mode 再 set_mode 一次，
    # 只在外面调 ui.set_mode 会被它覆盖掉（之前就是这么测错的）
    from valotalk.config import CONFIG
    CONFIG.set("ui.render_mode", mode, save=False)
    ui.set_mode(mode)

    from valotalk.app import App
    app = App()
    app._running = True
    for _ in range(12):
        app.root.update()

    # 1) 冷渲染：一整轮全树重绘
    t0 = time.time()
    app._repaint_tree(app.root)
    full = (time.time() - t0) * 1000

    # 2) 页面切换里的渲染函数累计（用 cProfile 抓）
    prof = cProfile.Profile()
    prof.enable()
    app._show_page("cfg")
    for _ in range(4):
        app.root.update()
    app._show_page("home")
    for _ in range(4):
        app.root.update()
    prof.disable()

    st = pstats.Stats(prof)
    total_render = 0.0
    detail = {}
    for (fn, line, func), (cc, nc, tt, ct, callers) in st.stats.items():
        name = Path(fn).name
        if name == "ui_theme.py" and func in (
                "glass_over_bg", "glass_image", "round_image", "bg_image",
                "_paint", "_redraw", "tint", "_tint_walk",
                "glass_equivalent_color", "card_inner_color",
                "flat_layers_color", "_eq_for"):
            detail[func] = (nc, ct * 1000)
            total_render += ct * 1000

    app.shutdown()
    return full, total_render, detail


with config_guard():
    rows = {}
    for mode in ("glass", "lite"):
        full, tot, det = measure(mode)
        rows[mode] = (full, tot, det)
        print(f"\n=== {mode} ===")
        print(f"  全树重绘一次      {full:8.1f} ms")
        print(f"  两次切页渲染累计   {tot:8.1f} ms")
        for k, (nc, ms) in sorted(det.items(), key=lambda x: -x[1][1])[:8]:
            print(f"    {k:24s} {nc:5d} 次  {ms:8.1f} ms")

    g = rows["glass"][1]
    l = rows["lite"][1]
    print("\n" + "=" * 56)
    if l > 0:
        print(f"切页渲染耗时：glass {g:.0f} ms → lite {l:.0f} ms "
              f"（快 {g / l:.1f}×）")
    print("=" * 56)
