"""对比日→中翻译质量：LLM vs Bing vs Google。

用真实 VALORANT 日语战术语句，看哪个译得准。
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.config import CONFIG
from valotalk.translate import Translator

CASES = [
    "Aサイトに敵、フランクに注意。",
    "ウルト使うから、カバーして。",
    "Bにラッシュ来てる、ローテートしよう。",
    "残りHP少ない、詰めて。",
    "オペレーター持ってる、出ないで。",
    "スパイク解除に行くから、カバーしてくれ。",
    "相手エコーだから、慎重に。",
    "敵が裏から来てる、気をつけて。",
]

print("日→中 翻译质量对比\n")
print("=" * 92)

results = {}
for backend in ("llm", "bing", "google"):
    t = Translator(CONFIG.get)
    # 强制单一后端：清空其他
    if backend == "llm":
        if not CONFIG.get("translate.llm.api_key"):
            print("llm: 没有 API key，跳过")
            continue
    print(f"\n--- {backend} ---")
    outs = []
    total = 0.0
    for text in CASES:
        t.backend_used = ""
        t._last_error = ""
        t0 = time.time()
        try:
            # 直接调指定后端
            if backend == "llm":
                out = t._via_llm(text, "ja", "zh-CN")
            elif backend == "bing":
                out = t._via_bing(text, "ja", "zh-CN")
            else:
                out = t._via_google(text, "ja", "zh-CN")
        except Exception as e:
            out = f"<{type(e).__name__}: {str(e)[:40]}>"
        dt = time.time() - t0
        total += dt
        outs.append(out or "<空>")
        print(f"  {text}")
        print(f"    → {out or '<空>'}   ({dt*1000:.0f}ms)")
    results[backend] = (outs, total / len(CASES))

print("\n" + "=" * 92)
print("并排对比：")
print(f"{'原文':<28s}{'llm':<26s}{'bing':<24s}{'google':<24s}")
print("-" * 92)
for i, text in enumerate(CASES):
    row = [text[:26]]
    for b in ("llm", "bing", "google"):
        if b in results:
            v = results[b][0][i]
            row.append(v[:24])
        else:
            row.append("—")
    print(f"{row[0]:<28s}{row[1]:<26s}{row[2]:<24s}{row[3]:<24s}")

print("\n平均耗时：")
for b, (_, avg) in results.items():
    print(f"  {b:8s} {avg*1000:6.0f} ms")