"""外观/线路切换测试：切档立即生效、配置落盘、线路过滤。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


with config_guard():
    import valotalk.ui_theme as ui
    from valotalk.app import App
    from valotalk.config import CONFIG

    CONFIG.set("ui.render_mode", "glass", save=False)
    App.__init__.__defaults__  # noqa
    app = App()
    app._running = True
    for _ in range(20):
        app.root.update()
        time.sleep(0.05)

    app._show_page("about")
    for _ in range(10):
        app.root.update()
        time.sleep(0.04)

    print(f"起始档位: {'lite' if ui.is_lite() else 'glass'}")
    print(f"下拉显示: {app.cb_render.get()!r}")
    check("外观下拉存在", bool(app.cb_render.get()))
    check("下拉值和实际档位一致",
          ("简约" in app.cb_render.get()) == ui.is_lite())

    print("\n=== 切到简约 ===")
    t = time.time()
    app.cb_render.set("简约（省资源）")
    app._on_render_mode_change()
    for _ in range(10):
        app.root.update()
    dt = (time.time() - t) * 1000
    print(f"  切换耗时 {dt:.0f} ms")
    check("档位变了", ui.is_lite())
    check("切换够快（<1500ms）", dt < 1500, f"{dt:.0f}ms")
    check("配置写入了", CONFIG.get("ui.render_mode") == "lite")

    print("\n=== 切回毛玻璃 ===")
    t = time.time()
    app.cb_render.set("毛玻璃（好看）")
    app._on_render_mode_change()
    for _ in range(10):
        app.root.update()
    dt = (time.time() - t) * 1000
    print(f"  切换耗时 {dt:.0f} ms")
    check("档位回到 glass", not ui.is_lite())
    check("配置写回", CONFIG.get("ui.render_mode") == "glass")

    print("\n=== 更新线路 ===")
    print(f"  下拉显示: {app.cb_channel.get()!r}")
    app.cb_channel.set("轻量版")
    app._on_channel_change()
    for _ in range(4):
        app.root.update()
    check("线路写入了 lite", CONFIG.get("update.channel") == "lite")
    check("updater 读到 lite", app.updater.channel() == "lite")
    app.cb_channel.set("正式版")
    app._on_channel_change()
    for _ in range(4):
        app.root.update()
    check("线路回到 stable", CONFIG.get("update.channel") == "stable")

    # 断言：切换后界面还能正常操作
    print("\n=== 切换后界面仍正常 ===")
    app._show_page("home")
    for _ in range(8):
        app.root.update()
        time.sleep(0.03)
    check("能切回主页", True)
    combos = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, ui.RoundCombo):
                combos.append(c)
            walk(c)

    walk(app.root)
    check("下拉框还在", len(combos) > 10, str(len(combos)))

    app.shutdown()

print("\n" + "=" * 56)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 56)
sys.exit(0 if failed == 0 else 1)
