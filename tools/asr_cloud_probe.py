"""探测 DashScope 的语音识别能力：哪些端点/模型能直接用于日语音频。

用现有 API key，试 OpenAI 兼容的 /audio/transcriptions 和 DashScope 原生接口。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from valotalk.config import CONFIG

KEY = CONFIG.get("translate.llm.api_key", "")
BASE = CONFIG.get("translate.llm.base_url", "")
print(f"base_url = {BASE}")
print(f"api_key  = {KEY[:12]}…（{len(KEY)} 字符）\n")

if not KEY:
    print("没有 API key")
    sys.exit(1)

# ---------- 1) 列可用模型 ----------
print("=== 1) DashScope 模型列表 ===")
try:
    r = requests.get(
        "https://dashscope.aliyuncs.com/api/v1/models",
        headers={"Authorization": f"Bearer {KEY}"}, timeout=20)
    print(f"  HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        names = [m.get("model") or m.get("name") for m in
                 (d.get("data") or d.get("models") or [])]
        asr_like = [n for n in names if n and any(
            k in n.lower() for k in ("asr", "paraformer", "sensevoice", "audio"))]
        print(f"  共 {len(names)} 个模型，语音相关：{asr_like[:20]}")
    else:
        print(f"  {r.text[:200]}")
except Exception as e:
    print(f"  {type(e).__name__}: {e}")

# ---------- 2) OpenAI 兼容的 audio/transcriptions ----------
print("\n=== 2) OpenAI 兼容 /audio/transcriptions ===")
import io
import wave
import numpy as np

# 造一段 1 秒的测试音频（不是真语音，只看端点认不认）
sr = 16000
t = np.arange(sr, dtype=np.float32) / sr
pcm = (0.2 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(pcm.tobytes())
wav_bytes = buf.getvalue()
print(f"  测试 wav: {len(wav_bytes)} B")

for model in ("qwen3-asr-flash", "paraformer-v2", "sensevoice-v1",
              "qwen-audio-asr", "whisper-1"):
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/audio/transcriptions"
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {KEY}"},
            files={"file": ("test.wav", wav_bytes, "audio/wav")},
            data={"model": model, "language": "ja"},
            timeout=45)
        body = r.text[:160].replace("\n", " ")
        print(f"  {model:18s} HTTP {r.status_code}  {body}")
    except Exception as e:
        print(f"  {model:18s} {type(e).__name__}: {str(e)[:60]}")

# ---------- 3) DashScope 原生 ASR（qwen3-asr-flash）----------
print("\n=== 3) DashScope 原生多模态接口 ===")
import base64
b64 = base64.b64encode(wav_bytes).decode()
for model in ("qwen3-asr-flash", "qwen-audio-asr"):
    try:
        r = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
            headers={"Authorization": f"Bearer {KEY}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "input": {"messages": [{"role": "user", "content": [
                      {"audio": f"data:audio/wav;base64,{b64}"}]}]}},
            timeout=45)
        print(f"  {model:18s} HTTP {r.status_code}  {r.text[:180]}")
    except Exception as e:
        print(f"  {model:18s} {type(e).__name__}: {str(e)[:60]}")