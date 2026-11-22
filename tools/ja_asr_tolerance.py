"""测 LLM 对「ASR 误识别」的容忍度。

如果 LLM 能从上下文纠正同音字错误，就不需要维护庞大的术语表。
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.config import CONFIG
from valotalk.translate import Translator

# (错误识别结果, 正确答案, 说明)
CASES = [
    ("売ると使うからカバー して。",      "我开大，掩护我。",     "ウルト→売ると"),
    ("売ると準備できてる。",            "大招好了。",           "ウルト→売ると"),
    ("Aサイトに敵、フランクに注意。",    "A点有敌人，小心绕后！", "正确识别"),
    ("スポイク設置した。",              "包放好了。",           "スパイク→スポイク"),
    ("オペ持ってる、出ないで。",         "有大狙，别出去。",      "オペレーター简称"),
    ("エコだから慎重に。",              "对面经济局，小心。",    "エコー→エコ"),
    ("残り hp少ない、詰めて。",         "血少，快压！",          "正确识别"),
    ("ろーてーとして。",                "转点。",               "ローテート→ろーてーと"),
]

t = Translator(CONFIG.get)
print("LLM 对误识别日语的纠正能力\n")
print("=" * 88)

ok = 0
for wrong, expect, note in CASES:
    out = ""
    try:
        out = t._via_llm(wrong, "ja", "zh-CN")
    except Exception as e:
        out = f"<{type(e).__name__}>"
    # 宽松匹配：期望答案的关键词
    keys = [k for k in expect.replace("，", " ").replace("！", " ").replace("。", " ").split() if k]
    hit = any(k in out for k in keys) if keys else False
    ok += 1 if hit else 0
    print(f"\n  [{note}]")
    print(f"    ASR 给:  {wrong}")
    print(f"    LLM 译:  {out}")
    print(f"    期望:    {expect}")
    print(f"    {'✓' if hit else '✗ 偏离'}")

print("\n" + "=" * 88)
print(f"{ok}/{len(CASES)} 条译对（宽松匹配）")

# 顺便看纯机翻对同样输入的表现
print("\n对比 Bing（同样输入）：")
for wrong, expect, note in CASES[:4]:
    try:
        out = t._via_bing(wrong, "ja", "zh-CN")
    except Exception as e:
        out = f"<{type(e).__name__}>"
    print(f"  {wrong:28s} → {out}")