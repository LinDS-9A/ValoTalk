"""术语纠正层测试：真实 ASR 错例 + 防误伤。"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.callouts import fix

# 视频里 whisper 真实输错的片段（左侧）→ 应该被纠成什么
CASES = [
    ("To a law, once law.", ["long", "slow"]),
    ("Retail die, retail die.", ["retreat"]),
    ("Watch flak.", ["flank"]),
    ("Spikes down eye.", ["spike"]),
    ("Smoking a short.", ["short"]),
    ("Eco round, save your money.", ["eco", "save"]),
    ("Flashing, don't look.", ["flash", "don't look"]),
    ("Trade me.", ["trade"]),
    ("I'm going in.", ["going in"]),
    ("Stick it.", ["stick"]),
    ("Two B main.", ["b main"]),
    ("Rotate B.", ["rotate"]),
]

# 不该被动的普通句子
NEGATIVE = [
    "i love you",
    "good morning everyone",
    "what time is it",
    "he is playing very well today",
    "let me think about it",
    "this is a nice house",
    "we should go home now",
    "she bought a new car",
    "the weather is really cold",
    "my computer is broken",
    # 专门防「裸 a long / a main 误伤」：这几个位置名和普通英语同形
    "it took a long time to finish",
    "we had a main course and dessert",
    "he is a long way from home",
    "that is a short story",
    "she is a little slow today",
    "the low price surprised me",
]

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}  {extra}")
        failed += 1


print("=== 应该被纠正的 ===")
for src, must in CASES:
    out, ch = fix(src)
    ok = all(m in out.lower() for m in must)
    print(f"  {src!r}")
    print(f"    -> {out!r}   改动 {ch}")
    check("   含 " + "/".join(must), ok, out)

print("\n=== 不该被动的普通句子 ===")
for s in NEGATIVE:
    out, ch = fix(s)
    check(s, out == s, f"被改成了 {out!r} {ch}")

print("\n=== 汇总 ===")
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
sys.exit(0 if failed == 0 else 1)
