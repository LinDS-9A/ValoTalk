"""用真实语音测 qwen3-asr-flash 的识别质量和延迟。

先用现成的英文样本验证链路，再看日语。
"""
from __future__ import annotations
import base64
import io
import json
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


def pcm_to_wav_b64(a: np.ndarray, sr: int = 16000) -> str:
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(a))) or 1.0
    a = a / max(peak, 1e-6) * 0.9
    pcm = (a * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return base64.b64encode(buf.getvalue()).decode()


def asr(b64: str, model: str = "qwen3-asr-flash") -> tuple[str, dict, float]:
    t0 = time.time()
    r = requests.post(
        URL,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"},
        json={"model": model,
              "input": {"messages": [{"role": "user", "content": [
                  {"audio": f"data:audio/wav;base64,{b64}"}]}]}},
        timeout=60)
    dt = time.time() - t0
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:150]}", {}, dt
    d = r.json()
    try:
        content = d["output"]["choices"][0]["message"]["content"]
        # content 可能是 [{"text": "..."}] 或空
        if isinstance(content, list):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        else:
            text = str(content)
    except Exception:
        text = json.dumps(d, ensure_ascii=False)[:200]
    return text.strip(), d.get("usage", {}), dt


print("=== 英文样本（缓存里的 TTS 产物）===")
for f in sorted((ROOT / "cache" / "tts").glob("*.mp3")):
    if f.stat().st_size < 2048:
        continue
    try:
        dec = miniaudio.decode_file(str(f),
                                    output_format=miniaudio.SampleFormat.FLOAT32,
                                    nchannels=1, sample_rate=16000)
        a = np.array(dec.samples, dtype=np.float32)
    except Exception:
        continue
    if a.size < 16000:
        continue
    print(f"\n  文件 {f.name}  {a.size/16000:.2f}s")
    b64 = pcm_to_wav_b64(a)
    text, usage, dt = asr(b64)
    print(f"    识别: {text!r}")
    print(f"    耗时 {dt:.2f}s  usage={usage}")
    break

print("\n=== 日语测试（用 edge-tts 现合成一句）===")
try:
    import asyncio
    import edge_tts
    out = ROOT / "cache" / "_ja_test.mp3"
    out.parent.mkdir(exist_ok=True)

    async def gen():
        c = edge_tts.Communicate("Aサイトに敵、フランクに注意。", "ja-JP-KeitaNeural")
        await c.save(str(out))

    asyncio.run(gen())
    dec = miniaudio.decode_file(str(out),
                                output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=1, sample_rate=16000)
    ja = np.array(dec.samples, dtype=np.float32)
    print(f"  合成 {ja.size/16000:.2f}s，原文: Aサイトに敵，フランクに注意。")

    b64 = pcm_to_wav_b64(ja)
    for attempt in (1, 2):
        text, usage, dt = asr(b64)
        print(f"  第{attempt}次 识别: {text!r}")
        print(f"         耗时 {dt:.2f}s  audio_tokens={usage.get('audio_tokens')}")
    out.unlink(missing_ok=True)
except Exception as e:
    print(f"  失败: {type(e).__name__}: {e}")

print("\n=== 对比：本地 whisper small ===")
from valotalk.asr import WhisperASR
w = WhisperASR(CONFIG.get)
if w.ensure_loaded(on_status=lambda s: print(f"  {s}")):
    if ja.size if 'ja' in dir() else False:
        t0 = time.time()
        txt = w.transcribe(ja, "ja")
        print(f"  本地日语: {txt!r}  耗时 {time.time()-t0:.2f}s")
else:
    print("  本地模型加载失败")