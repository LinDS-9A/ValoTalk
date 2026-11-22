"""DeepSeek ASR 真实日语识别：质量 + 延迟 + 与阿里云对比。"""
from __future__ import annotations
import io
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KEY = os.environ.get("DS_KEY", "")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache" / "_ds_test.mp3"

import asyncio
import edge_tts
import miniaudio

H = {"Authorization": f"Bearer {KEY}"}
DS_URL = "https://api.deepseek.com/v1/tools/asr"

DS_KEY_CFG = KEY


def to_wav(a, sr=16000):
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(a))) or 1.0
    a = a / max(peak, 1e-6) * 0.9
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def ds_asr(wav_bytes, sess):
    """DeepSeek ASR。文档里只有 file 字段，语言自动检测。"""
    t0 = time.time()
    r = sess.post(DS_URL, headers=H,
                  files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                  timeout=60)
    dt = time.time() - t0
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:100]}", dt
    d = r.json()
    return d.get("text", ""), dt


CASES = [
    ("Aサイトに敵、フランクに注意。", ["サイト", "敵"]),
    ("ウルト使うから、カバーして。", ["ウルト", "カバー"]),
    ("Bにラッシュ来てる、ローテートしよう。", ["ラッシュ", "ローテート"]),
    ("残りHP少ない、詰めて。", ["HP"]),
    ("オペレーター持ってる、出ないで。", ["オペレーター"]),
    ("敵が裏から来てる、気をつけて。", ["敵", "裏"]),
]

sess = requests.Session()
print("DeepSeek ASR 日语识别\n")
print("=" * 84)
print(f"{'原文':<26s}{'识别结果':<30s}{'延迟':>8s}{'关键词':>8s}")
print("-" * 84)

ok = 0
total = 0.0
for text, keys in CASES:
    async def gen(t=text):
        c = edge_tts.Communicate(t, "ja-JP-KeitaNeural")
        await c.save(str(OUT))
    asyncio.run(gen())
    dec = miniaudio.decode_file(str(OUT),
                                output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=1, sample_rate=16000)
    wav = to_wav(np.array(dec.samples, dtype=np.float32))

    got, dt = ds_asr(wav, sess)
    total += dt
    hit = sum(1 for k in keys if k.lower() in got.lower())
    good = hit >= max(1, len(keys) - 1)
    ok += 1 if good else 0
    print(f"{text[:24]:<26s}{got[:28]:<30s}{dt:7.2f}s"
          f"{hit}/{len(keys):>6} {'✓' if good else '✗'}")

OUT.unlink(missing_ok=True)

print("-" * 84)
print(f"{ok}/{len(CASES)} 条识别正确    平均延迟 {total/len(CASES):.2f}s")

print("\n=== 第二次（连接复用后）===")
times = []
for text, _ in CASES[:3]:
    async def gen(t=text):
        c = edge_tts.Communicate(t, "ja-JP-KeitaNeural")
        await c.save(str(OUT))
    asyncio.run(gen())
    dec = miniaudio.decode_file(str(OUT),
                                output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=1, sample_rate=16000)
    wav = to_wav(np.array(dec.samples, dtype=np.float32))
    _, dt = ds_asr(wav, sess)
    times.append(dt)
    print(f"  {text[:20]:<22s} {dt:.2f}s")
OUT.unlink(missing_ok=True)
if times:
    print(f"  平均 {sum(times)/len(times):.2f}s")