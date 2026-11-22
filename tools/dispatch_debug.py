"""复现 dispatch_test 的翻译失败：在 App 上下文里调 translator。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

with config_guard():
    from valotalk.app import App

    app = App()
    app._running = True
    print("App 已启动\n")

    t = app.translator
    for lang in ("en", "ja"):
        order = t._backend_order(lang, "zh-CN")
        print(f"_backend_order({lang!r}, 'zh-CN') = {order}")

    print("\n--- 直接调 translator.translate ---")
    for text, src, dst in (
        ("Rush B, plant the spike behind the box.", "en", "zh-CN"),
        ("掩护我，我要开大了", "zh", "en"),
    ):
        t0 = time.time()
        out = t.translate(text, src, dst)
        print(f"  {src}→{dst}: {out!r}  ({time.time()-t0:.2f}s) "
              f"backend={t.backend_used}")
        if t.last_error:
            print(f"    last_error: {t.last_error[:120]}")

    print("\n--- 走 _dispatch ---")
    from valotalk.app import Job
    app._dispatch(Job(kind="teammates",
                      text="Rush B, plant the spike behind the box."))
    app.root.update()
    print(f"  字幕: {app.overlay.items[-1].text if app.overlay.items else '(空)'}")
    print(f"  last_error: {app.translator.last_error[:160]}")

    app.shutdown()