"""检查当前配置下翻译是否可用（key 是否还有效）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.config import CONFIG
from valotalk.translate import Translator

print("当前配置:")
print("  base_url:", CONFIG.get("translate.llm.base_url"))
print("  model:", CONFIG.get("translate.llm.model"))
k = CONFIG.get("translate.llm.api_key", "")
print("  api_key:", f"{k[:12]}…（{len(k)} 字符）" if k else "(空)")
print("  translate.backend:", CONFIG.get("translate.backend"))
print("  asr.backend:", CONFIG.get("asr.backend"))

t = Translator(CONFIG.get)
for text, src, dst in (
    ("Rush B, plant the spike behind the box.", "en", "zh-CN"),
    ("掩护我，我要开大了", "zh", "en"),
):
    print(f"\n--- {src}→{dst}: {text[:40]} ---")
    order = t._backend_order(src, dst)
    print(f"  后端顺序: {order}")
    t0 = time.time()
    try:
        out = t.translate(text, src, dst)
        dt = time.time() - t0
        print(f"  结果: {out!r}  ({dt:.2f}s)  backend={t.backend_used}")
    except Exception as e:
        print(f"  异常: {type(e).__name__}: {e}")
    if t.last_error:
        print(f"  last_error: {t.last_error[:150]}")