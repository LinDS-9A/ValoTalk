"""截下拉框外观：静止状态 + 展开状态。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

from PIL import ImageGrab

OUT = Path(__file__).resolve().parent.parent / "cache"

with config_guard():
    from valotalk.app import App
    import valotalk.ui_theme as ui

    app = App()
    app._running = True
    for _ in range(28):
        app.root.update()
        time.sleep(0.07)

    # 主页有 游戏服务器 / TTS音色 / 风格 三个下拉
    app._show_page("home")
    for _ in range(14):
        app.root.update()
        time.sleep(0.05)
    app.root.update_idletasks()

    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()

    # 找下拉框
    combos = []

    def walk(wd):
        for c in wd.winfo_children():
            if isinstance(c, ui.RoundCombo):
                combos.append(c)
            walk(c)

    walk(app.root)
    print(f"下拉框 {len(combos)} 个")

    # 1) 静止状态：放大某个下拉
    if combos:
        c = combos[1] if len(combos) > 1 else combos[0]
        cx, cy = c.winfo_rootx(), c.winfo_rooty()
        cw, ch = c.winfo_width(), c.winfo_height()
        im = ImageGrab.grab(bbox=(cx - 4, cy - 4, cx + cw + 4, cy + ch + 4))
        im.resize((im.width * 3, im.height * 3), 1).save(
            OUT / "shot_combo_closed.png")
        print(f"存 shot_combo_closed.png  ({cw}x{ch} 放大 3 倍)")

        # 2) 展开状态
        c._open()
        for _ in range(10):
            app.root.update()
            time.sleep(0.06)
        if c._pop:
            px, py = c._pop.winfo_rootx(), c._pop.winfo_rooty()
            pw, ph = c._pop.winfo_width(), c._pop.winfo_height()
            print(f"弹出层 ({px},{py}) {pw}x{ph}")
            im2 = ImageGrab.grab(bbox=(px - 8, py - 8, px + pw + 8,
                                       py + ph + 8))
            im2.resize((im2.width * 2, im2.height * 2), 1).save(
                OUT / "shot_combo_open.png")
            print("存 shot_combo_open.png（放大 2 倍）")
            c._close()

    # 3) 整页
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(OUT / "shot_home.png")
    print("存 shot_home.png")

    app.shutdown()
