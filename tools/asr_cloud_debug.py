"""找出 qwen3-asr-flash 返回空的原因：逐步减去可选字段。"""
from __future__ import annotations
import base64
import io
import json
import sys
import wave
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.config import CONFIG
import miniaudio

KEY = CONFIG.get("translate.llm.api_key", "")
URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache" / "_dbg.mp3"


def to_b64(a, sr=16000):
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(a))) or 1.0
    a = a / max(peak, 1e-6) * 0.9
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((a * 32767).astype(np.int16).tobytes())
    return base64.b64encode(buf.getvalue()).decode()


import asyncio
import edge_tts


async def gen():
    c = edge_tts.Communicate("Aサイトに敵、フランクに注意。", "ja-JP-KeitaNeural")
    await c.save(str(OUT))


asyncio.run(gen())
dec = miniaudio.decode_file(str(OUT), output_format=miniaudio.SampleFormat.FLOAT32,
                            nchannels=1, sample_rate=16000)
audio = np.array(dec.samples, dtype=np.float32)
b64 = to_b64(audio)
print(f"音频 {audio.size/16000:.2f}s, b64 {len(b64)} 字符\n")

sess = requests.Session()
sess.headers.update({"Authorization": f"Bearer {KEY}",
                     "Content-Type": "application/json"})

VARIANTS = [
    ("最小请求（之前成功的）", {
        "model": "qwen3-asr-flash",
        "input": {"messages": [{"role": "user", "content": [
            {"audio": f"data:audio/wav;base64,{b64}"}]}]},
    }),
    ("+ parameters.language", {
        "model": "qwen3-asr-flash",
        "input": {"messages": [{"role": "user", "content": [
            {"audio": f"data:audio/wav;base64,{b64}"}]}]},
        "parameters": {"language": "ja"},
    }),
    ("+ 文本提示", {
        "model": "qwen3-asr-flash",
        "input": {"messages": [{"role": "user", "content": [
            {"audio": f"data:audio/wav;base64,{b64}"},
            {"text": "以下是 VALORANT 日语语音。"}]}]},
    }),
    ("+ asr_options", {
        "model": "qwen3-asr-flash",
        "input": {"messages": [{"role": "user", "content": [
            {"audio": f"data:audio/wav;base64,{b64}"}]}]},
        "parameters": {"asr_options": {"language": "ja", "enable_lid": True}},
    }),
]

for name, payload in VARIANTS:
    try:
        r = sess.post(URL, json=payload, timeout=45)
        print(f"--- {name} ---")
        print(f"  HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"  {r.text[:220]}")
            continue
        d = r.json()
        # 打印关键结构
        out = d.get("output", {})
        ch = out.get("choices", [])
        print(f"  output keys: {list(out.keys())}")
        if ch:
            msg = ch[0].get("message", {})
            print(f"  message keys: {list(msg.keys())}")
            print(f"  content = {json.dumps(msg.get('content'), ensure_ascii=False)[:200]}")
        print(f"  usage = {json.dumps(d.get('usage'), ensure_ascii=False)[:150]}")
    except Exception as e:
        print(f"--- {name} --- ERROR {type(e).__name__}: {e}")
    print()

OUT.unlink(missing_ok=True)