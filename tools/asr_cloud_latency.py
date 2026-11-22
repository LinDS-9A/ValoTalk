"""测 qwen3-asr-flash 对不同长度音频的延迟，判断能不能用于实时字幕。"""
from __future__ import annotations
import base64
import io
import sys
import time
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


def asr(b64, session):
    t0 = time.time()
    r = session.post(URL, headers={"Authorization": f"Bearer {KEY}"},
                     json={"model": "qwen3-asr-flash",
                           "input": {"messages": [{"role": "user", "content": [
                               {"audio": f"data:audio/wav;base64,{b64}"}]}]}},
                     timeout=60)
    dt = time.time() - t0
    if r.status_code != 200:
        return None, dt, r.status_code
    try:
        c = r.json()["output"]["choices"][0]["message"]["content"]
        if isinstance(c, list):
            return " ".join(x.get("text", "") for x in c if isinstance(x, dict)), dt, 200
        return str(c), dt, 200
    except Exception:
        return "", dt, 200


# 准备几段不同长度的日语
import asyncio
import edge_tts

TEXTS = [
    "敵、A。",                                                   # 极短
    "Aサイトに敵、フランクに注意。",                                  # 中等
    "Bにラッシュ来てる、ロートードしよう。残りHP少ないから詰めて。",       # 长
]

sess = requests.Session()
print("qwen3-asr-flash 延迟测试（复用连接）\n")
print(f"{'音频时长':>9s}{'第1次':>9s}{'第2次':>9s}{'第3次':>9s}   识别结果")
print("-" * 76)

for text in TEXTS:
    out = ROOT / "cache" / "_asr_probe.mp3"
    out.parent.mkdir(exist_ok=True)
    try:
        async def gen(t=text):
            c = edge_tts.Communicate(t, "ja-JP-KeitaNeural")
            await c.save(str(out))
        asyncio.run(gen())
        dec = miniaudio.decode_file(str(out),
                                    output_format=miniaudio.SampleFormat.FLOAT32,
                                    nchannels=1, sample_rate=16000)
        a = np.array(dec.samples, dtype=np.float32)
    except Exception as e:
        print(f"  合成失败: {e}")
        continue

    b64 = to_b64(a)
    times = []
    result = ""
    for i in range(3):
        txt, dt, code = asr(b64, sess)
        times.append(dt)
        if txt is not None:
            result = txt
    dur = f"{a.size/16000:.2f}s"
    tstr = "".join(f"{t:8.2f}s" for t in times)
    print(f"{dur:>9s}{tstr}   {result[:40]!r}")
    out.unlink(missing_ok=True)

print("\n结论参考：端到端延迟 = VAD收尾 + ASR + 翻译 + TTS")
print("            本地 whisper 识别约 0.35s，云端见上表")