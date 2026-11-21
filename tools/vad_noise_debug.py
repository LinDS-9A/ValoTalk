"""调试：噪声突变时每轮 _extract 的噪声估计来源。"""
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
orig = seg._update_noise
log = []


def spy(noise):
    before = seg.noise_rms
    buf_len = seg.buf.size / SR
    orig(noise)
    log.append((noise, before, seg.noise_rms, seg.cur_gap_s * 1000, buf_len))


seg._update_noise = spy

for phase, rms in [("安静", 0.004), ("枪战", 0.080), ("安静下来", 0.004)]:
    print(f"--- {phase} (rms={rms}) ---")
    audio = burst_noise(1.0, rms, seed=3) if rms > 0 else \
        np.zeros(int(SR * 1.0), dtype=np.float32)
    block = int(SR * 30 / 1000)
    n0 = len(log)
    for i in range(0, audio.size, block):
        seg.feed(audio[i:i + block])
    for noise, before, after, gap, blen in log[n0:]:
        print(f"    测得 {noise:.4f}  EMA {before:.4f}→{after:.4f}  "
              f"gap {gap:.0f}ms  缓冲 {blen:.2f}s")