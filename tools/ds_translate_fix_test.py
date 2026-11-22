"""验证 _via_llm 修复：DeepSeek 下不再返回空、延迟降低，且兼容不支持该参数的接口。"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.config import CONFIG
from valotalk.translate import Translator

KEY = os.environ.get("DS_KEY", "")
failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


# 备份原配置
_orig = {k: CONFIG.get(k) for k in
         ("translate.llm.base_url", "translate.llm.model",
          "translate.llm.api_key")}

print("=== 1) DeepSeek deepseek-flash ===")
CONFIG.set("translate.llm.base_url", "https://api.deepseek.com/v1", save=False)
CONFIG.set("translate.llm.model", "deepseek-flash", save=False)
CONFIG.set("translate.llm.api_key", KEY, save=False)

t = Translator(CONFIG.get)
CASES = [
    ("エコだから慎重に。", "经济"),
    ("相手エコだから慎重に。", "经济"),
    ("Aサイトに敵、フランクに注意。", "绕后"),
    ("オペレーター持ってる、出ないで。", "大狙"),
    ("ウルト使うから、カバーして。", "大招"),
]

times = []
empty = 0
ok = 0
for text, key in CASES:
    t0 = time.time()
    out = t._via_llm(text, "ja", "zh-CN")
    dt = time.time() - t0
    times.append(dt)
    if not out:
        empty += 1
    good = key in out
    ok += 1 if good else 0
    print(f"  {text[:22]:<24s} {dt:5.2f}s  {out[:22]!r} {'✓' if good else '✗'}")

print(f"  平均 {sum(times)/len(times):.2f}s")
check("没有空结果", empty == 0, f"{empty} 条空")
check("全部语义正确", ok == len(CASES), f"{ok}/{len(CASES)}")
check("平均延迟 < 1.0s", sum(times) / len(times) < 1.0,
      f"{sum(times)/len(times):.2f}s")

print("\n=== 2) 换成 deepseek-v4-pro ===")
CONFIG.set("translate.llm.model", "deepseek-v4-pro", save=False)
t2 = Translator(CONFIG.get)
t0 = time.time()
out = t2._via_llm("Aサイトに敵、フランクに注意。", "ja", "zh-CN")
dt = time.time() - t0
print(f"  {dt:.2f}s  {out!r}")
check("v4-pro 也能译出", bool(out), out)

print("\n=== 3) 不支持 thinking 参数的接口要能降级 ===")
# 用阿里云（不认 thinking 参数）验证降级路径
_ali = {k: CONFIG.get(k) for k in
        ("translate.llm.base_url", "translate.llm.model",
         "translate.llm.api_key")}
CONFIG.set("translate.llm.base_url",
           "https://dashscope.aliyuncs.com/compatible-mode/v1", save=False)
CONFIG.set("translate.llm.model", "qwen-plus", save=False)
CONFIG.set("translate.llm.api_key",
           _orig.get("translate.llm.api_key") or "", save=False)
t3 = Translator(CONFIG.get)
t0 = time.time()
try:
    out3 = t3._via_llm("Aサイトに敵、フランクに注意。", "ja", "zh-CN")
    dt = time.time() - t0
    print(f"  阿里云 {dt:.2f}s  {out3!r}")
    check("降级后仍能翻译", bool(out3), out3)
except Exception as e:
    print(f"  异常: {type(e).__name__}: {e}")
    check("降级后仍能翻译", False, str(e))

# 还原
for k, v in _orig.items():
    CONFIG.set(k, v or "", save=False)

print("\n" + "=" * 52)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 52)
sys.exit(0 if failed == 0 else 1)