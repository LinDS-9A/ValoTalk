"""探测 DeepSeek（以及其它常见服务）有没有 ASR 端点。

用 HTTP 状态码判断：404 = 端点不存在，401/403 = 存在但需要认证。
"""
from __future__ import annotations
import io
import wave

import numpy as np
import requests

# 造一个最小 wav
sr = 16000
pcm = (0.2 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr) * 32767).astype(np.int16)
buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(pcm.tobytes())
WAV = buf.getvalue()

TARGETS = [
    ("DeepSeek /v1/audio/transcriptions", "https://api.deepseek.com/v1/audio/transcriptions"),
    ("DeepSeek /v1/audio/speech", "https://api.deepseek.com/v1/audio/speech"),
    ("OpenAI /v1/audio/transcriptions", "https://api.openai.com/v1/audio/transcriptions"),
    ("硅基流动 /v1/audio/transcriptions",
     "https://api.siliconflow.cn/v1/audio/transcriptions"),
    ("阿里兼容模式 /audio/transcriptions",
     "https://dashscope.aliyuncs.com/compatible-mode/v1/audio/transcriptions"),
    ("火山 /api/v3/audio/transcriptions",
     "https://ark.cn-beijing.volces.com/api/v3/audio/transcriptions"),
]

print("探测 ASR 端点是否存在（不带 key，看状态码）\n")
print(f"{'服务':<42s}{'HTTP':>6s}  判断")
print("-" * 78)

for name, url in TARGETS:
    try:
        r = requests.post(
            url,
            files={"file": ("t.wav", WAV, "audio/wav")},
            data={"model": "whisper-1"},
            timeout=20)
        code = r.status_code
        if code == 404:
            verdict = "端点不存在（不支持 ASR）"
        elif code in (401, 403):
            verdict = "端点存在（需要认证）"
        elif code == 400:
            verdict = "端点存在（参数不对）"
        else:
            verdict = r.text[:60].replace("\n", " ")
        print(f"{name:<42s}{code:>6d}  {verdict}")
    except requests.exceptions.Timeout:
        print(f"{name:<42s}  TIMEOUT")
    except Exception as e:
        print(f"{name:<42s}  {type(e).__name__}: {str(e)[:40]}")