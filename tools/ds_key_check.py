"""用真实 DeepSeek key 验证 ASR 能力。

key 从环境变量 DS_KEY 读，不落盘、不打日志。
"""
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
if not KEY:
    print("缺少 DS_KEY 环境变量")
    sys.exit(1)

print(f"key: {KEY[:6]}…{KEY[-4:]}（{len(KEY)} 字符）\n")
H = {"Authorization": f"Bearer {KEY}"}

print("=== 1) key 有效性 ===")
try:
    r = requests.get("https://api.deepseek.com/v1/models", headers=H, timeout=25)
    print(f"  GET /v1/models → HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        names = [m.get("id") for m in d.get("data", [])]
        print(f"  可用模型: {names}")
except Exception as e:
    print(f"  {type(e).__name__}: {e}")

print("\n=== 2) ASR 端点（静音）===")
sr = 16000
pcm = np.zeros(sr, dtype=np.int16)
buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(pcm.tobytes())
WAV = buf.getvalue()

try:
    t0 = time.time()
    r = requests.post("https://api.deepseek.com/v1/tools/asr",
                      headers=H,
                      files={"file": ("audio.wav", WAV, "audio/wav")},
                      timeout=60)
    dt = time.time() - t0
    print(f"  POST /v1/tools/asr → HTTP {r.status_code}  {dt:.2f}s")
    print(f"  {r.text[:300]}")
except Exception as e:
    print(f"  {type(e).__name__}: {e}")