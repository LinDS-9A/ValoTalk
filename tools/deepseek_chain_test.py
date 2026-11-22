"""验证切到 DeepSeek 后：云端 ASR 预热、识别、翻译全链路。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.asr_cloud import CloudASR, fix_ja_terms
from valotalk.config import CONFIG
from valotalk.translate import Translator

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache" / "_switch.mp3"

import asyncio
import edge_tts
import miniaudio

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


print("当前配置:")
print("  translate.llm.base_url:", CONFIG.get("translate.llm.base_url"))
print("  translate.llm.model   :", CONFIG.get("translate.llm.model"))
k = CONFIG.get("translate.llm.api_key", "")
print("  api_key 长度:", len(k))
print("  asr.cloud_provider:", repr(CONFIG.get("asr.cloud_provider")))
print("  asr.backend:", CONFIG.get("asr.backend"))

print("\n=== 1) CloudASR 描述与预热 ===")
asr = CloudASR(CONFIG.get, log=print)
print(f"  provider={asr.provider}  base={asr.base_url}  model={asr.model!r}")
check("识别为 deepseek", asr.provider == "deepseek", asr.provider)
check("用 DeepSeek 地址", "deepseek.com" in asr.base_url, asr.base_url)

t0 = time.time()
ok = asr.warmup()
print(f"  预热 {'成功' if ok else '失败'} {time.time()-t0:.2f}s  {asr.last_error}")
check("预热成功（不再是 401）", ok, asr.last_error)

print("\n=== 2) 日语识别 ===")
CASES = [
    ("Aサイトに敵、フランクに注意。", ["サイト", "敵"]),
    ("ウルト使うから、カバーして。", ["ウルト", "カバー"]),
    ("残りHP少ない、詰めて。", ["HP"]),
]
for text, keys in CASES:
    async def gen(t=text):
        c = edge_tts.Communicate(t, "ja-JP-KeitaNeural")
        await c.save(str(OUT))
    asyncio.run(gen())
    dec = miniaudio.decode_file(str(OUT),
                                output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=1, sample_rate=16000)
    pcm = np.array(dec.samples, dtype=np.float32)
    asr.transcribe(pcm, "ja")
    t0 = time.time()
    got = asr.transcribe(pcm, "ja")
    dt = time.time() - t0
    fixed = fix_ja_terms(got)
    hit = sum(1 for x in keys if x.lower() in fixed.lower())
    print(f"  {text[:22]:<24s} {dt:5.2f}s  {got!r} → {fixed!r}")
    check(f"识别命中 {hit}/{len(keys)}", hit >= 1, got)
OUT.unlink(missing_ok=True)
asr.close()

print("\n=== 3) DeepSeek 翻译 ===")
tr = Translator(CONFIG.get)
TJ = [
    ("Aサイトに敵、フランクに注意。", "绕后"),
    ("ウルト使うから、カバーして。", "大招"),
    ("オペレーター持ってる、出ないで。", "大狙"),
]
for text, key in TJ:
    t0 = time.time()
    out = tr._via_llm(text, "ja", "zh-CN")
    dt = time.time() - t0
    print(f"  {text[:22]:<24s} {dt:5.2f}s  {out!r}")
    check(f"译文含「{key}」", key in out, out)

print("\n=== 4) 英文翻译（英服链路）===")
t0 = time.time()
out = tr.translate("Rush B, plant the spike behind the box.", "en", "zh-CN")
dt = time.time() - t0
print(f"  {dt:.2f}s  {out!r}  backend={tr.backend_used}")
check("英→中能译出", bool(out), out)
check("走的是 LLM", tr.backend_used == "llm", tr.backend_used)

print("\n" + "=" * 52)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 52)
sys.exit(0 if failed == 0 else 1)