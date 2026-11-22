"""探测 asr_options 支持哪些参数 —— 想给云端 ASR 加游戏术语提示。"""
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
OUT = ROOT / "cache" / "_hw.mp3"


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


async def gen(t):
    c = edge_tts.Communicate(t, "ja-JP-KeitaNeural")
    await c.save(str(OUT))


# 用那句容易错的
asyncio.run(gen("ウルト使うから、カバーして。"))
dec = miniaudio.decode_file(str(OUT), output_format=miniaudio.SampleFormat.FLOAT32,
                            nchannels=1, sample_rate=16000)
b64 = to_b64(np.array(dec.samples, dtype=np.float32))

sess = requests.Session()
sess.headers.update({"Authorization": f"Bearer {KEY}",
                     "Content-Type": "application/json"})

base_input = {"messages": [{"role": "user", "content": [
    {"audio": f"data:audio/wav;base64,{b64}"}]}]}

VARIANTS = [
    ("无参数", {}),
    ("language=ja", {"asr_options": {"language": "ja"}}),
    ("+ hotwords", {"asr_options": {"language": "ja",
                                    "hotwords": ["ウルト", "サイト", "スパイク"]}}),
    ("+ context", {"asr_options": {"language": "ja",
                                   "context": "VALORANT: ウルト サイト スパイク フランク"}}),
    ("+ vocabulary", {"asr_options": {"language": "ja",
                                      "vocabulary": ["ウルト", "スパイク"]}}),
    ("+ hotword_list", {"asr_options": {"language": "ja",
                                        "hotword_list": ["ウルト"]}}),
    ("顶层 hotwords", {"hotwords": ["ウルト", "サイト"]}),
]

print("原文: ウルト使うから、カバーして。\n")
for name, params in VARIANTS:
    payload = {"model": "qwen3-asr-flash", "input": base_input}
    if params:
        payload["parameters"] = params
    try:
        r = sess.post(URL, json=payload, timeout=45)
        if r.status_code != 200:
            print(f"{name:16s} HTTP {r.status_code}  {r.text[:140]}")
            continue
        d = r.json()
        ch = d.get("output", {}).get("choices", [])
        text = ""
        if ch:
            c = ch[0].get("message", {}).get("content")
            if isinstance(c, list):
                text = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            else:
                text = str(c or "")
        ok = "ウルト" in text
        print(f"{name:16s} {'✓' if ok else ' '} {text!r}")
    except Exception as e:
        print(f"{name:16s} ERROR {type(e).__name__}: {str(e)[:60]}")

OUT.unlink(missing_ok=True)