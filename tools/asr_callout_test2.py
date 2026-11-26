"""进一步测：不加 / 长 initial_prompt / 短 prompt / hotwords。"""
from __future__ import annotations
import av
import numpy as np
from pathlib import Path

SRC = Path(r"C:\Users\小林\.dsh\douyin-duty\media\lab"
           r"\7698793274546375946-1795506121\source.mp4")
LOCAL = (r"E:\rea-work\valotalk\models\models--Systran--faster-whisper-small"
         r"\snapshots\536b0662742c02347bc0e980a01041f333bce120")

KEYS = ["eco", "save", "long", "slow", "retreat", "smok", "flash",
        "don't look", "going in", "trade", "flank", "spike", "default",
        "half", "stick"]

LONG = ("VALORANT team voice chat on HK/Asia server. Common callouts: "
        "A main, B main, mid, long, short, heaven, site, spike, "
        "rotate, eco round, full buy, save, default, flank, trade, "
        "one shot, half, stick it, defusing, cover me.")
SHORT = "VALORANT callouts: A main, B main, mid, long, short, spike."
HOT = "A main, B main, mid, long, short, heaven, spike, rotate, eco, save, flank, trade, half, stick"


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
    return np.concatenate(out).astype(np.float32) / 32768.0


from faster_whisper import WhisperModel

m = WhisperModel(LOCAL, device="cpu", compute_type="int8", local_files_only=True)
audio = load_audio(255.0, 280.0)
print(f"音频 {len(audio)/16000:.1f}s\n")


def run(tag, **kw):
    try:
        segs, _ = m.transcribe(audio, language="en", vad_filter=True,
                               beam_size=1, **kw)
        txt = " | ".join(s.text.strip() for s in segs if s.text.strip())
    except TypeError as e:
        txt = f"(该参数不支持: {e})"
    low = txt.lower()
    hit = sum(1 for k in KEYS if k in low)
    print(f"--- {tag} ---")
    print(f"  {txt}")
    print(f"  命中 {hit}/{len(KEYS)}\n")
    return hit


import time

for tag, kw in (
    ("① 什么都不加", {}),
    ("② 长 initial_prompt", {"initial_prompt": LONG}),
    ("③ 短 initial_prompt", {"initial_prompt": SHORT}),
    ("④ hotwords（正确的术语偏置接口）", {"hotwords": HOT}),
):
    t = time.time()
    run(tag, **kw)
    print(f"    耗时 {time.time()-t:.1f}s\n")
