"""查 _frameless 为什么没设上。"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

with config_guard():
    from valotalk.config import CONFIG

    print("ui.frameless =", repr(CONFIG.get("ui.frameless", "（没有这个键）")))

    from valotalk.app import App
    from valotalk import winapi

    app = App()
    app._running = True
    for _ in range(8):
        app.root.update()

    print("app._frameless =", app._frameless)
    print("hasattr _frameless =", hasattr(app, "_frameless"))

    hwnd = winapi.top_level_hwnd(app.root)
    print("hwnd =", hex(hwnd))

    # 手动再跑一次，看返回值
    print("strip_caption 返回:", winapi.strip_caption(hwnd))
    print("keep_shadow 返回:", winapi.keep_shadow(hwnd))
    print("现在 _frameless =", app._frameless)

    # 直接看 _build_ui 里那段是否会执行
    import inspect
    src = inspect.getsource(App._build_ui)
    idx = src.find("strip_caption")
    print("\n_build_ui 里 strip_caption 附近：")
    print(src[max(0, idx - 420):idx + 160])

    app.shutdown()