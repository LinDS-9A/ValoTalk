"""端到端：视频真实报点 → 程序自己的 WhisperASR → 看识别和纠正效果。"""
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

KEYS = ["eco", "save", "long", "slow", "retreat", "smok", "flash",
        "don't look", "going in", "trade", "flank", "spike", "default",
        "half", "stick"]


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


CFG = {"asr.model": "small", "asr.device": "cpu", "asr.beam_size": 1}


def cfg_get(key, default=None):
    return CFG.get(key, default)


audio = load_audio(255.0, 280.0)
print(f"音频 {len(audio)/16000:.1f}s")

# 关掉纠正，先看原始识别
orig_fix = callouts.fix
callouts.fix = lambda t: (t, [])          # 临时旁路，拿"纠正前"的基准

from valotalk.asr import WhisperASR

asr = WhisperASR(cfg_get)
t = time.time()
ok = asr.ensure_loaded()
print(f"模型加载 {'成功' if ok else '失败：' + str(asr.load_error)}  "
      f"{time.time()-t:.1f}s")
if not ok:
    sys.exit(1)

t = time.time()
before = asr.transcribe(audio, "en")
dt1 = time.time() - t

callouts.fix = orig_fix                      # 恢复
t = time.time()
after = asr.transcribe(audio, "en")
dt2 = time.time() - t
corr = getattr(asr, "last_corrections", [])

print(f"\n【纠正前】{before}")
print(f"【纠正后】{after}")
print(f"【纠正记录】{corr}")
print(f"\n耗时 {dt1*1000:.0f}ms / {dt2*1000:.0f}ms（含模型热身后）")

low_b, low_a = before.lower(), after.lower()
hb = sum(1 for k in KEYS if k in low_b)
ha = sum(1 for k in KEYS if k in low_a)
print(f"\n关键词命中：{hb}/{len(KEYS)} → {ha}/{len(KEYS)}")
