"""终极校验：两个档位各自能起来、耗时、界面完整。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard


def run(mode: str):
    import valotalk.ui_theme as ui
    from valotalk.config import CONFIG
    from valotalk.app import App

    CONFIG.set("ui.render_mode", mode, save=False)
    t0 = time.time()
    app = App()
    app._running = True
    for _ in range(10):
        app.root.update()
    build = time.time() - t0

    pages = {}
    for pg in ("cfg", "about", "home"):
        t = time.time()
        app._show_page(pg)
        for _ in range(6):
            app.root.update()
        pages[pg] = (time.time() - t) * 1000

    # 界面完整性：控件数量 + 卡片数量
    combos = cards = 0

    def walk(w):
        nonlocal combos, cards
        for c in w.winfo_children():
            if isinstance(c, ui.RoundCombo):
                combos += 1
            elif isinstance(c, ui.RoundCard):
                cards += 1
            walk(c)

    walk(app.root)
    is_lite = ui.is_lite()
    app.shutdown()
    return build, pages, combos, cards, is_lite


with config_guard():
    for mode in ("glass", "lite"):
        b, pages, combos, cards, is_lite = run(mode)
        print(f"\n=== {mode} ===")
        print(f"  档位生效      {'lite' if is_lite else 'glass'}"
              f"  {'✓' if (mode == 'lite') == is_lite else '✗'}")
        print(f"  构建+10帧     {b:6.2f} s")
        print(f"  切页          " + "  ".join(
            f"{k} {v:.0f}ms" for k, v in pages.items()))
        print(f"  下拉 {combos} 个 / 卡片 {cards} 个")
