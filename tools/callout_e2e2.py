"""按真实用法测：切成 2 秒左右的小段喂给程序自己的 ASR。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import av
import numpy as np

from valotalk import callouts

SRC = Path(r"C:\Users\小林\.dsh\douyin-duty\media\lab"
           r"\7698793274546375946-1795506121\source.mp4")

# (起, 止, 人工听写的真值)
CLIPS = [
    (256.2, 258.2, "Eco round, save your money"),
    (258.2, 260.2, "To A long, one slow"),
    (260.2, 262.2, "Retreat, retreat"),
    (264.2, 266.2, "Smoking A short"),
    (266.2, 268.2, "Flashing, don't look"),
    (270.2, 271.2, "Trade me"),
    (271.2, 273.2, "Watch flank"),
    (273.2, 274.2, "Spike's down"),
]


def load_audio(a, b):
    c = av.open(str(SRC))
    st = next(s for s in c.streams if s.type == "audio")
    res = av.AudioResampler(format="s16", layout="mono", rate=16000)
    out = []
    for pkt in c.demux(st):
        for f in pkt.decode():
            t0 = float(f.pts * st.time_base) if f.pts is not None else 0
            t1 = t0 + f.samples / float(f.sample_rate or 16000)
            if t1 < a or t0 > b:
                continue
            for rf in res.resample(f):
                out.append(rf.to_ndarray().reshape(-1))
    c.close()
    a2 = np.concatenate(out).astype(np.float32) / 32768.0
    # 裁到窗口内
    return a2[: int((b - a) * 16000)]


CFG = {"asr.model": "small", "asr.device": "cpu", "asr.beam_size": 1}
from valotalk.asr import WhisperASR

asr = WhisperASR(lambda k, d=None: CFG.get(k, d))
print("加载模型…", flush=True)
if not asr.ensure_loaded():
    print("失败", asr.load_error)
    sys.exit(1)

orig_fix = callouts.fix
print(f"{'真值':<28}{'纠正前':<34}{'纠正后'}")
print("-" * 100)
hit_b = hit_a = 0
total = 0
for a, b, truth in CLIPS:
    audio = load_audio(a, b)

    callouts.fix = lambda t: (t, [])           # 旁路纠正
    before = asr.transcribe(audio, "en")
    callouts.fix = orig_fix
    after = asr.transcribe(audio, "en")
    corr = getattr(asr, "last_corrections", []) or []

    kw = [w.lower().strip(".,") for w in truth.split() if len(w) > 3]
    total += len(kw)
    hit_b += sum(1 for w in kw if w in before.lower())
    hit_a += sum(1 for w in kw if w in after.lower())
    print(f"{truth:<28}{before.strip():<34}{after.strip()}")
    if corr:
        print(f"{'':<28}↳ 纠正 {corr}")

print("-" * 100)
print(f"关键词命中：{hit_b}/{total} → {hit_a}/{total}")
