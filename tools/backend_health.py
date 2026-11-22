"""单独验证 Bing / Google / MyMemory 当前是否可用（排除限流）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.config import CONFIG
from valotalk.translate import Translator

t = Translator(CONFIG.get)
TEXT = "Rush B, plant the spike behind the box."

for name, fn in (("bing", t._via_bing), ("google", t._via_google),
                 ("mymemory", t._via_mymemory)):
    print(f"\n--- {name} ---")
    for i in range(3):
        t0 = time.time()
        try:
            out = fn(TEXT, "en", "zh-CN")
            dt = time.time() - t0
            print(f"  #{i+1} {dt:5.2f}s  {out!r}")
        except Exception as e:
            print(f"  #{i+1} {type(e).__name__}: {str(e)[:100]}")
        time.sleep(1.2)