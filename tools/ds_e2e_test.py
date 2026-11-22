"""DeepSeek 一条龙：ASR + 翻译，端到端延迟和质量。"""
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
OUT = ROOT / "cache" / "_ds_e2e.mp3"
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

import asyncio
import edge_tts
import miniaudio

# 复用 session
S = requests.Session()
S.headers.update({"Authorization": f"Bearer {KEY}"})


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


def ds_asr(wav):
    t0 = time.time()
    r = S.post("https://api.deepseek.com/v1/tools/asr",
               files={"file": ("a.wav", wav, "audio/wav")}, timeout=60)
    dt = time.time() - t0
    if r.status_code != 200:
        return f"<HTTP {r.status_code}>", dt
    return r.json().get("text", ""), dt


SYS = (
    "你是 VALORANT 游戏内的实时翻译。把日语队友语音翻成简体中文。\n"
    "术语固定译法：サイト=包点、スパイク=炸弹/包、ウルト=大招、"
    "エコー/エコ=经济局、フランク=绕后、ローテート=转点、"
    "オペレーター/オペ=大狙、カバー=掩护、ラッシュ=一波冲。\n"
    "只输出译文，不要解释，不要加引号。口语化、简短。"
)


def ds_translate(text, model="deepseek-flash"):
    t0 = time.time()
    r = S.post("https://api.deepseek.com/v1/chat/completions",
               json={"model": model,
                     "messages": [{"role": "system", "content": SYS},
                                  {"role": "user", "content": text}],
                     "temperature": 0, "max_tokens": 120},
               timeout=60)
    dt = time.time() - t0
    if r.status_code != 200:
        return f"<HTTP {r.status_code}: {r.text[:80]}>", dt
    d = r.json()
    try:
        return d["choices"][0]["message"]["content"].strip(), dt
    except Exception:
        return "<解析失败>", dt


CASES = [
    ("Aサイトに敵、フランクに注意。", "绕后"),
    ("ウルト使うから、カバーして。", "大招"),
    ("Bにラッシュ来てる、ローテートしよう。", "转点"),
    ("残りHP少ない、詰めて。", "血"),
    ("オペレーター持ってる、出ないで。", "大狙"),
    ("相手エコーだから、慎重に。", "经济"),
]

print("DeepSeek 端到端：日语语音 → ASR → 翻译\n")
print("=" * 92)
print(f"{'原文':<24s}{'识别':<24s}{'译文':<24s}{'耗时':>10s}")
print("-" * 92)

ok = 0
t_asr_all, t_tr_all = [], []
for text, key in CASES:
    async def gen(t=text):
        c = edge_tts.Communicate(t, "ja-JP-KeitaNeural")
        await c.save(str(OUT))
    asyncio.run(gen())
    dec = miniaudio.decode_file(str(OUT),
                                output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=1, sample_rate=16000)
    wav = to_wav(np.array(dec.samples, dtype=np.float32))

    heard, ta = ds_asr(wav)
    zh, tt = ds_translate(heard) if not heard.startswith("<") else ("", 0)
    t_asr_all.append(ta)
    t_tr_all.append(tt)
    good = key in zh
    ok += 1 if good else 0
    print(f"{text[:22]:<24s}{heard[:22]:<24s}{zh[:22]:<24s}"
          f"{ta+tt:7.2f}s {'✓' if good else '✗'}")

OUT.unlink(missing_ok=True)

print("-" * 92)
print(f"{ok}/{len(CASES)} 条语义正确")
print(f"平均：ASR {sum(t_asr_all)/len(t_asr_all):.2f}s  "
      f"翻译 {sum(t_tr_all)/len(t_tr_all):.2f}s  "
      f"合计 {sum(t_asr_all)/len(t_asr_all)+sum(t_tr_all)/len(t_tr_all):.2f}s")
print(f"端到端估算（+VAD 240ms + TTS 300ms）："
      f"{(sum(t_asr_all)/len(t_asr_all)+sum(t_tr_all)/len(t_tr_all))*1000+540:.0f}ms")

print("\n=== 对比 deepseek-v4-pro ===")
t_pro, t_flash = [], []
for text, _ in CASES[:3]:
    _, dt1 = ds_translate(text, "deepseek-flash")
    _, dt2 = ds_translate(text, "deepseek-v4-pro")
    t_flash.append(dt1)
    t_pro.append(dt2)
    print(f"  {text[:20]:<22s} flash {dt1:.2f}s   v4-pro {dt2:.2f}s")
print(f"  平均：flash {sum(t_flash)/len(t_flash):.2f}s  "
      f"v4-pro {sum(t_pro)/len(t_pro):.2f}s")