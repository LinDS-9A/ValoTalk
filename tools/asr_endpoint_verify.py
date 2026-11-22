"""用假 key 区分「真没有这个端点」和「网关先拦认证」。

- 报 invalid api key → 认证层拦截，无法证明端点存在
- 报 not found / unknown endpoint → 端点不存在
"""
from __future__ import annotations
import io
import json

import numpy as np
import requests
import wave

sr = 16000
pcm = (0.2 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr) * 32767).astype(np.int16)
buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(pcm.tobytes())
WAV = buf.getvalue()

FAKE = "sk-proj-FAKEKEYFORTESTING0000000000000000000000000000000000"

TARGETS = [
    ("DeepSeek  audio", "https://api.deepseek.com/v1/audio/transcriptions",
     {"model": "whisper-1"}),
    ("DeepSeek  chat（对照）", "https://api.deepseek.com/v1/chat/completions", None),
    ("DeepSeek  不存在的路径", "https://api.deepseek.com/v1/nonexistent_xyz",
     {"model": "x"}),
    ("硅基流动  audio", "https://api.siliconflow.cn/v1/audio/transcriptions",
     {"model": "FunAudioLLM/SenseVoiceSmall"}),
    ("硅基流动  不存在的路径", "https://api.siliconflow.cn/v1/nonexistent_xyz", None),
]

for name, url, data in TARGETS:
    try:
        if data is None:
            r = requests.post(url,
                              headers={"Authorization": f"Bearer {FAKE}",
                                       "Content-Type": "application/json"},
                              json={"model": "x", "messages": []}, timeout=20)
        else:
            r = requests.post(url,
                              headers={"Authorization": f"Bearer {FAKE}"},
                              files={"file": ("t.wav", WAV, "audio/wav")},
                              data=data, timeout=20)
        body = r.text[:220].replace("\n", " ")
        print(f"{name:<26s} HTTP {r.status_code}")
        print(f"    {body}")
    except Exception as e:
        print(f"{name:<26s} {type(e).__name__}: {str(e)[:60]}")
    print()