"""验证日服大模型链路：云端 ASR 选择 + 翻译不降级。

不真的联网识别（那要等），重点验证调度逻辑和配置分支。
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App
from valotalk.config import CONFIG
from valotalk.translate import Translator

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


print("=== 1) 翻译后端顺序：日语不降级 ===")
t = Translator(CONFIG.get)
cases = [
    ("ja", "zh-CN", "日→中 应该只走 llm"),
    ("zh", "ja", "中→日 应该只走 llm"),
    ("en", "zh-CN", "英→中 允许机翻兜底"),
]
for src, dst, note in cases:
    order = t._backend_order(src, dst)
    print(f"  {src} → {dst}: {order}   ({note})")
    if src.startswith("ja") or dst.startswith("ja"):
        check(f"{src}→{dst} 只有 llm", order == ["llm"], str(order))
    else:
        check(f"{src}→{dst} 含多后端", len(order) > 1, str(order))

print("\n=== 2) backend=bing 时日语也不走 bing ===")
CONFIG.set("translate.backend", "bing", save=False)
order = t._backend_order("ja", "zh-CN")
print(f"  ja→zh-CN: {order}")
check("即使设了 bing，有 LLM 时日语也不降级",
      order == ["llm"], str(order))

# 没配 LLM 时才允许机翻兜底
_orig_base = CONFIG.get("translate.llm.base_url")
CONFIG.set("translate.llm.base_url", "", save=False)
order2 = t._backend_order("ja", "zh-CN")
print(f"  没有 LLM 时 ja→zh-CN: {order2}")
check("无 LLM 时退回机翻（有总比没有好）", len(order2) > 0, str(order2))
CONFIG.set("translate.llm.base_url", _orig_base, save=False)
CONFIG.set("translate.backend", "auto", save=False)

print("\n=== 3) 云端 ASR 选择逻辑 ===")
app = App()
app._running = True
for _ in range(20):
    app.root.update()
    time.sleep(0.06)


def set_backend(b):
    CONFIG.set("asr.backend", b, save=False)


# 现在只有两态：cloud / local（auto 视为 cloud，兼容老配置）
set_backend("cloud")
print(f"  cloud + 日语 → 用云端: {app._use_cloud_asr('ja')}")
check("cloud 日语走云端", app._use_cloud_asr("ja") is True)
print(f"  cloud + 英语 → 用云端: {app._use_cloud_asr('en')}")
check("cloud 英语也走云端（开关对两个服务器都生效）",
      app._use_cloud_asr("en") is True)

set_backend("local")
print(f"  local + 日语 → 用云端: {app._use_cloud_asr('ja')}")
check("local 强制本地", app._use_cloud_asr("ja") is False)
print(f"  local + 英语 → 用云端: {app._use_cloud_asr('en')}")
check("local 英服也本地", app._use_cloud_asr("en") is False)

set_backend("auto")
print(f"  auto（老配置）+ 英语 → {app._use_cloud_asr('en')}")
check("auto 兼容为云端", app._use_cloud_asr("en") is True)
set_backend("cloud")

print("\n=== 4) 云端失败时降级到本地 ===")
# 临时让云端必定失败
_orig = app.asr_cloud.transcribe
app.asr_cloud.transcribe = lambda pcm, lang=None: ""
app.asr_cloud.last_error = "模拟失败"
CONFIG.set("asr.cloud_fallback", True, save=False)

class J:
    kind = "teammates"
    pcm = np.zeros(16000, dtype=np.float32)
    text = ""
    detected_lang = None
    asr_backend = ""

job = J()
# 让本地 ASR 返回固定文本
_orig_local = app.asr.transcribe
app.asr.transcribe = lambda pcm, lang=None: "local-fallback-text"
app.asr.loaded = True

text = app._transcribe(job, "ja")
print(f"  返回: {text!r}  backend={job.asr_backend}")
check("云端失败后本地接手", text == "local-fallback-text", text)
check("backend 标记为 local", job.asr_backend == "local", job.asr_backend)

# 关闭 fallback 时不该有结果
CONFIG.set("asr.cloud_fallback", False, save=False)
job2 = J()
text2 = app._transcribe(job2, "ja")
print(f"  关掉 fallback 后: {text2!r}")
check("关掉 fallback 就返回空", text2 == "", text2)
CONFIG.set("asr.cloud_fallback", True, save=False)

app.asr.transcribe = _orig_local
app.asr_cloud.transcribe = _orig

print("\n=== 5) 云端成功时不该碰本地 ===")
app.asr_cloud.transcribe = lambda pcm, lang=None: "cloud-text"
called = {"n": 0}
app.asr.transcribe = lambda pcm, lang=None: (called.__setitem__("n", called["n"]+1), "x")[1]
job3 = J()
text3 = app._transcribe(job3, "ja")
print(f"  返回: {text3!r}  backend={job3.asr_backend}  本地被调用 {called['n']} 次")
check("用云端结果", text3 == "cloud-text", text3)
check("backend 标记为 cloud", job3.asr_backend == "cloud")
check("本地没被调用", called["n"] == 0, str(called["n"]))
app.asr_cloud.transcribe = _orig
app.asr.transcribe = _orig_local

print("\n=== 6) 配置项都在 ===")
for key in ("asr.backend", "asr.cloud_model", "asr.cloud_timeout",
            "asr.cloud_fallback"):
    v = CONFIG.get(key)
    print(f"  {key} = {v!r}")
    check(f"有 {key}", v is not None)

app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)