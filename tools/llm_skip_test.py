"""验证 LLM 是否真的会输出 [SKIP]（这是方案能否成立的关键）。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

# 特工语音（规则表没覆盖的长句，专测 LLM 兜底）
AGENT_LONG = [
    "The enemy fears you, Reyna.",
    "Kill their leader and the rest will flee like rats.",
    "So the German has some fancy toys. Let's break them!",
    "I'll kill that Omen. I'll take his memories.",
    "Do you see under my hood, Cypher?",
]

# 队友报点（必须翻译）
TEAMMATE = [
    "Two B main",
    "Rotate A now",
    "He's low, one shot",
    "Watch flank, someone behind us",
]

with config_guard():
    from valotalk.config import CONFIG
    from valotalk.translate import Translator

    t = Translator(lambda k, d=None: CONFIG.get(k, d))

    print("=== 特工语音长句（期望 [SKIP]）===")
    skip_ok = 0
    for s in AGENT_LONG:
        try:
            out = t.translate(s, "en", "zh-CN")
        except Exception as e:
            out = f"(错误: {e})"
        tok = out.strip().upper().strip("[]【】（）() ")
        is_skip = tok in ("SKIP", "跳过")
        skip_ok += 1 if is_skip else 0
        flag = "SKIP" if is_skip else "翻译"
        print(f"  [{flag:6s}] {s}")
        if not is_skip:
            print(f"           -> {out}")
        time.sleep(0.3)

    print("\n=== 队友报点（期望正常翻译）===")
    keep_ok = 0
    for s in TEAMMATE:
        try:
            out = t.translate(s, "en", "zh-CN")
        except Exception as e:
            out = f"(错误: {e})"
        tok = out.strip().upper().strip("[]【】（）() ")
        is_skip = tok in ("SKIP", "跳过")
        keep_ok += 1 if not is_skip else 0
        flag = "跳过!" if is_skip else "翻译"
        print(f"  [{flag:6s}] {s}  ->  {out}")
        time.sleep(0.3)

    print(f"\n特工语音识别为 SKIP: {skip_ok}/{len(AGENT_LONG)}")
    print(f"队友报点正常翻译:   {keep_ok}/{len(TEAMMATE)}")
