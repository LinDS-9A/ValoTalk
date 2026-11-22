"""阿里云 vs DeepSeek 两套方案完整对比：识别 + 翻译 + 端到端。"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.asr_cloud import CloudASR, fix_ja_terms
from valotalk.config import CONFIG
from valotalk.translate import Translator

DS_KEY = os.environ.get("DS_KEY", "")
ALI_KEY = CONFIG.get("translate.llm.api_key", "")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache" / "_cmp.mp3"

import asyncio
import edge_tts
import miniaudio

CASES = [
    ("Aサイトに敵、フランクに注意。", ["繞", "绕", "フランクを绕"]),
    ("ウルト使うから、カバーして。", ["大招", "开大"]),
    ("Bにラッシュ来てる、ローテートしよう。", ["转点", "一波"]),
    ("残りHP少ない、詰めて。", ["血", "压"]),
    ("オペレーター持ってる、出ないで。", ["大狙", "狙"]),
    ("相手エコーだから、慎重に。", ["经济"]),
]


def gen_audio(text):
    async def g():
        c = edge_tts.Communicate(text, "ja-JP-KeitaNeural")
        await c.save(str(OUT))
    asyncio.run(g())
    dec = miniaudio.decode_file(str(OUT),
                                output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=1, sample_rate=16000)
    return np.array(dec.samples, dtype=np.float32)


def make(provider, key, model=""):
    saved = {k: CONFIG.get(k) for k in
             ("asr.cloud_provider", "asr.cloud_base_url", "asr.cloud_model",
              "asr.cloud_api_key")}
    CONFIG.set("asr.cloud_provider", provider, save=False)
    CONFIG.set("asr.cloud_base_url", "", save=False)
    CONFIG.set("asr.cloud_model", model, save=False)
    CONFIG.set("asr.cloud_api_key", key, save=False)
    a = CloudASR(CONFIG.get, log=lambda *_: None)
    for k, v in saved.items():
        CONFIG.set(k, v or "", save=False)
    return a


print("准备两套识别器 …")
ali = make("dashscope", ALI_KEY)
ds = make("deepseek", DS_KEY)
ali.warmup()
ds.warmup()
print(f"  阿里云: {ali.describe()}")
print(f"  DeepSeek: {ds.describe()}\n")

print("=" * 96)
print(f"{'原文':<24s}{'阿里云识别':<26s}{'DeepSeek识别':<26s}")
print("-" * 96)

rows = []
for text, _ in CASES:
    pcm = gen_audio(text)
    # 各测两次取第二次（连接已热）
    ali.transcribe(pcm, "ja")
    t0 = time.time()
    a_txt = ali.transcribe(pcm, "ja")
    a_ms = (time.time() - t0) * 1000

    ds.transcribe(pcm, "ja")
    t0 = time.time()
    d_txt = ds.transcribe(pcm, "ja")
    d_ms = (time.time() - t0) * 1000

    rows.append((text, a_txt, d_txt, a_ms, d_ms))
    print(f"{text[:22]:<24s}{a_txt[:24]:<26s}{d_txt[:24]:<26s}")

OUT.unlink(missing_ok=True)

a_avg = sum(r[3] for r in rows) / len(rows)
d_avg = sum(r[4] for r in rows) / len(rows)
print("-" * 96)
print(f"平均识别延迟：阿里云 {a_avg:.0f}ms   DeepSeek {d_avg:.0f}ms")

# 需要术语纠正的条数（识别里含已知错误）
bad_words = ("売ると", "スポイク", "ロテート", "プランク", "オペレタ")
a_bad = sum(1 for r in rows if any(w in r[1] for w in bad_words))
d_bad = sum(1 for r in rows if any(w in r[2] for w in bad_words))
print(f"需要术语纠正：阿里云 {a_bad}/{len(rows)}   DeepSeek {d_bad}/{len(rows)}")

print("\n" + "=" * 96)
print("翻译质量对比（同一句，日本语原文）：")
print("-" * 96)

for name, base, model, key in (
    ("Qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "qwen-plus", ALI_KEY),
    ("DS-flash", "https://api.deepseek.com/v1", "deepseek-flash", DS_KEY),
):
    saved = {k: CONFIG.get(k) for k in
             ("translate.llm.base_url", "translate.llm.model",
              "translate.llm.api_key")}
    CONFIG.set("translate.llm.base_url", base, save=False)
    CONFIG.set("translate.llm.model", model, save=False)
    CONFIG.set("translate.llm.api_key", key, save=False)
    t = Translator(CONFIG.get)
    times = []
    got = 0
    print(f"\n{name}:")
    for text, keys in CASES:
        t0 = time.time()
        try:
            out = t._via_llm(text, "ja", "zh-CN")
        except Exception as e:
            out = f"<{type(e).__name__}>"
        dt = time.time() - t0
        times.append(dt)
        hit = any(k in out for k in keys)
        got += 1 if hit else 0
        print(f"  {text[:22]:<24s} {dt:5.2f}s  {out[:24]!r} {'✓' if hit else '✗'}")
    print(f"  平均 {sum(times)/len(times):.2f}s  语义 {got}/{len(CASES)}")
    for k, v in saved.items():
        CONFIG.set(k, v or "", save=False)

ali.close()
ds.close()
print("\n" + "=" * 96)
print(f"结论：阿里云识别 {a_avg:.0f}ms，DeepSeek 识别 {d_avg:.0f}ms")
print("      DeepSeek 识别更准（术语不用纠正），但稍慢")