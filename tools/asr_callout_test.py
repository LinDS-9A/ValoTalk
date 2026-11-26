"""拿视频里的真实报点，测 ValoTalk 的英文识别与翻译。

对比：不加术语提示 vs 加术语提示；看识别错在哪、翻译错在哪。
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

import av
import numpy as np

SRC = Path(r"C:\Users\小林\.dsh\douyin-duty\media\lab"
           r"\7698793274546375946-1795506121\source.mp4")
LOCAL = (r"E:\rea-work\valotalk\models\models--Systran--faster-whisper-small"
         r"\snapshots\536b0662742c02347bc0e980a01041f333bce120")

# 视频里"实战测试"那段的真实报点（人工听写，来自转写稿）
TRUTH = [
    "Eco round", "Save your money", "To A long", "One slow",
    "Retreat", "Smoking A short", "Flashing", "Don't look",
    "I'm going in", "Trade me", "Watch flank", "Spike's down",
    "Default", "Half", "Stick it",
]

PROMPT_EN = ("VALORANT team voice chat on HK/Asia server. Common callouts: "
             "A main, B main, mid, long, short, heaven, site, spike, "
             "rotate, eco round, full buy, save, default, flank, trade, "
             "one shot, half, stick it, defusing, cover me.")


def load_audio(start_s: float, end_s: float):
    container = av.open(str(SRC))
    st = next(s for s in container.streams if s.type == "audio")
    res = av.AudioResampler(format="s16", layout="mono", rate=16000)
    out = []
    for packet in container.demux(st):
        for frame in packet.decode():
            t0 = float(frame.pts * st.time_base) if frame.pts is not None else 0
            t1 = t0 + (frame.samples / float(frame.sample_rate or 16000))
            if t1 < start_s or t0 > end_s:
                continue
            for rf in res.resample(frame):
                out.append(rf.to_ndarray().reshape(-1))
    container.close()
    a = np.concatenate(out).astype(np.float32) / 32768.0
    return a


from faster_whisper import WhisperModel

print("加载本地 small 模型…")
m = WhisperModel(LOCAL, device="cpu", compute_type="int8", local_files_only=True)

audio = load_audio(255.0, 280.0)
print(f"测试音频 {len(audio)/16000:.1f}s\n")


def run(prompt, tag):
    segs, _ = m.transcribe(audio, language="en", vad_filter=True,
                           beam_size=1, initial_prompt=prompt)
    txt = " | ".join(s.text.strip() for s in segs if s.text.strip())
    print(f"--- {tag} ---")
    print(f"  {txt}\n")
    return txt.lower()


a = run(None, "① 不加任何提示（当前程序的行为）")
b = run(PROMPT_EN, "② 加术语提示")

print("=== 关键词命中对比 ===")
KEYS = ["eco", "save", "long", "slow", "retreat", "smok", "flash",
        "don't look", "going in", "trade", "flank", "spike", "default",
        "half", "stick"]
for label, txt in (("无提示", a), ("有提示", b)):
    hit = sum(1 for k in KEYS if k in txt)
    print(f"  {label}: {hit}/{len(KEYS)}  得分 {hit/len(KEYS)*100:.0f}%")

print("\n=== 逐句看差别（只列两边不一致的）===")
print(f"  真值共 {len(TRUTH)} 句")
