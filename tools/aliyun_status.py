"""确认当前配置是阿里云，以及 key 是否有效。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.asr_cloud import CloudASR
from valotalk.config import CONFIG
from valotalk.translate import Translator

print("=== 配置 ===")
print("  translate.llm.base_url:", CONFIG.get("translate.llm.base_url"))
print("  translate.llm.model   :", CONFIG.get("translate.llm.model"))
k = CONFIG.get("translate.llm.api_key", "")
print("  api_key               :", f"{k[:12]}…（{len(k)} 字符）" if k else "(空)")
print("  asr.backend           :", CONFIG.get("asr.backend"))
print("  asr.cloud_provider    :", repr(CONFIG.get("asr.cloud_provider")))

a = CloudASR(CONFIG.get, log=lambda *_: None)
print("\n=== 云端 ASR ===")
print("  provider:", a.provider)
print("  base_url:", a.base_url)
print("  model   :", a.model)
print("  有 key  :", a.available())
ok = a.warmup()
print("  预热    :", "成功" if ok else "失败")
if not ok:
    print("  错误    :", a.last_error[:180])
a.close()

print("\n=== LLM 翻译 ===")
t = Translator(CONFIG.get)
try:
    out = t._via_llm("Rush B, plant the spike.", "en", "zh-CN")
    print(f"  结果: {out!r}")
except Exception as e:
    print(f"  异常: {type(e).__name__}: {str(e)[:150]}")

print("\n=== 兜底链路（机翻）===")
t0 = t.translate("Rush B, plant the spike behind the box.", "en", "zh-CN")
print(f"  结果: {t0!r}  backend={t.backend_used}")