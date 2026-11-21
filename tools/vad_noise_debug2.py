"""深入调试：_noise_outside 拿到什么窗口、spans 覆盖哪里。"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk import capture

SR = 16000
CFG = {
    "silero_threshold": 0.5,
    "silero_min_speech_ms": 300,
    "silero_min_silence_ms": 220,
    "silero_pad_ms": 120,
    "silero_window_s": 12.0,
    "max_utterance_ms": 9000,
    "adaptive_gap": True,
}


def burst_noise(sec, rms, seed=0):
    rng = np.random.default_rng(seed)
    n = int(SR * sec)
    base = rng.standard_normal(n).astype(np.float32)
    env = np.zeros(n, dtype=np.float32)
    step = int(SR * 0.15)
    for i in range(0, n, step):
        L = min(step, n - i)
        env[i:i + L] = np.hanning(L)
    sig = base * env * 3.0
    cur = float(np.sqrt(np.mean(sig ** 2)) + 1e-12)
    return (sig * (rms / cur)).astype(np.float32)


seg = capture.SileroSegmenter(CFG)

orig = seg._noise_outside


def spy(window, spans):
    val = orig(window, spans)
    wn = window.size / SR
    tail_n = int(SR * 0.8)
    recent = window[-tail_n:] if window.size > tail_n else window
    recent_rms = float(np.sqrt(np.mean(recent ** 2) + 1e-12))
    span_desc = [(round(s["start"] / SR, 2), round(s["end"] / SR, 2)) for s in spans]
    print(f"    _noise_outside: window={wn:.2f}s  recent自算RMS={recent_rms:.4f}  "
          f"返回={val:.4f}  spans={span_desc}")
    return val


seg._noise_outside = spy

for phase, rms in [("安静", 0.004), ("枪战", 0.080), ("安静下来", 0.004)]:
    print(f"--- {phase} (rms={rms}) ---")
    audio = burst_noise(1.0, rms, seed=3) if rms > 0 else \
        np.zeros(int(SR * 1.0), dtype=np.float32)
    block = int(SR * 30 / 1000)
    for i in range(0, audio.size, block):
        seg.feed(audio[i:i + block])