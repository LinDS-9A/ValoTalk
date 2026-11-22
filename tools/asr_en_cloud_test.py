"""测英文音频的云端识别延迟，和本地 whisper 对比。

决定「大模型识别」开关的默认值：如果英文云端也不慢，默认开就没问题。
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.asr_cloud import CloudASR
from valotalk.config import CONFIG

ROOT = Path(__file__).resolve().parent.parent
import miniaudio

# 用缓存里现成的英文 TTS
pcm = None
for f in sorted((ROOT / "cache" / "tts").glob("*.mp3")):
    if f.stat().st_size < 2048:
        continue
    try:
        d = miniaudio.decode_file(str(f),
                                  output_format=miniaudio.SampleFormat.FLOAT32,
                                  nchannels=1, sample_rate=16000)
        a = np.array(d.samples, dtype=np.float32)
    except Exception:
        continue
    if a.size > 16000:
        pcm = a
        print(f"英文样本: {f.name}  {a.size/16000:.2f}s")
        break

if pcm is None:
    print("没有英文样本")
    sys.exit(1)

print("\n=== 云端（阿里云）===")
ali = CloudASR(CONFIG.get, log=print)
ali.warmup()
times = []
for _ in range(3):
    t0 = time.time()
    txt = ali.transcribe(pcm, "en")
    times.append(time.time() - t0)
print(f"  识别: {txt!r}")
print(f"  延迟: " + "  ".join(f"{t*1000:.0f}ms" for t in times))
print(f"  中位 {sorted(times)[1]*1000:.0f}ms")
ali.close()

print("\n=== 本地 whisper ===")
from valotalk.asr import WhisperASR

w = WhisperASR(CONFIG.get)
if w.ensure_loaded(on_status=lambda s: print(f"  {s}")):
    w.transcribe(pcm, "en")          # 预热
    times2 = []
    for _ in range(3):
        t0 = time.time()
        txt2 = w.transcribe(pcm, "en")
        times2.append(time.time() - t0)
    print(f"  识别: {txt2!r}")
    print(f"  延迟: " + "  ".join(f"{t*1000:.0f}ms" for t in times2))
    print(f"  中位 {sorted(times2)[1]*1000:.0f}ms")
    print(f"\n云端比本地慢 {sorted(times)[1]/sorted(times2)[1]:.1f} 倍")
else:
    print("  本地模型加载失败")