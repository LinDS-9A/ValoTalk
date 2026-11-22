"""日服完整链路真实验证：日语语音 → 云端大模型识别 → LLM 翻译。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.asr_cloud import CloudASR, fix_ja_terms
from valotalk.config import CONFIG
from valotalk.translate import Translator
import asyncio
import edge_tts
import miniaudio

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache" / "_e2e_ja.mp3"

CASES = [
    ("Aサイトに敵、フランクに注意。", "A点有敌人"),
    ("ウルト使うから、カバーして。", "开大"),
    ("Bにラッシュ来てる、ローテートしよう。", "转点"),
    ("残りHP少ない、詰めて。", "血"),
    ("オペレーター持ってる、出ないで。", "大狙"),
]

asr = CloudASR(CONFIG.get, log=print)
tr = Translator(CONFIG.get)

print("预热云端 ASR …")
t0 = time.time()
asr.warmup()
print(f"  {time.time()-t0:.2f}s\n")

print("=" * 88)
print(f"{'日语原句':<26s}{'云端识别':<28s}{'LLM 译文':<24s}{'耗时':>8s}")
print("-" * 88)

total_t = []
ok = 0
for text, expect_key in CASES:
    async def gen(t=text):
        c = edge_tts.Communicate(t, "ja-JP-KeitaNeural")
        await c.save(str(OUT))
    asyncio.run(gen())
    dec = miniaudio.decode_file(str(OUT),
                                output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=1, sample_rate=16000)
    pcm = np.array(dec.samples, dtype=np.float32)

    t0 = time.time()
    heard_raw = asr.transcribe(pcm, "ja")
    heard = fix_ja_terms(heard_raw)      # 加上术语纠正
    t_asr = time.time() - t0
    if heard != heard_raw:
        print(f"  〔纠错〕{heard_raw} → {heard}")

    t0 = time.time()
    zh = ""
    if heard:
        try:
            zh = tr._via_llm(heard, "ja", "zh-CN")
        except Exception as e:
            zh = f"<{type(e).__name__}>"
    t_tr = time.time() - t0

    hit = expect_key in zh if zh else False
    ok += 1 if hit else 0
    total_t.append((t_asr, t_tr))
    print(f"{text[:24]:<26s}{heard[:26]:<28s}{zh[:22]:<24s}"
          f"{t_asr+t_tr:7.2f}s {'✓' if hit else '✗'}")

OUT.unlink(missing_ok=True)

print("-" * 88)
a = sum(x[0] for x in total_t) / len(total_t)
t = sum(x[1] for x in total_t) / len(total_t)
print(f"{ok}/{len(CASES)} 条语义正确")
print(f"平均：云端识别 {a*1000:.0f}ms  LLM 翻译 {t*1000:.0f}ms  "
      f"合计 {(a+t)*1000:.0f}ms")
print(f"\n端到端估算（加上 VAD 收尾 240ms + TTS 300ms）："
      f"{(a+t)*1000+240+300:.0f}ms")

asr.close()
sys.exit(0 if ok >= len(CASES) - 1 else 1)