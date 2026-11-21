"""测自适应 VAD 的 CPU 开销：加急轮询（120ms）会不会太耗。

对比固定 300ms 轮询 vs 语音期间切 120ms 轮询的 Silero 调用次数和耗时。
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk import capture

ROOT = Path(__file__).resolve().parent.parent
SR = 16000

CFG_SLOW = {
    "silero_threshold": 0.5, "silero_min_speech_ms": 300,
    "silero_min_silence_ms": 220, "silero_pad_ms": 120,
    "silero_window_s": 12.0, "max_utterance_ms": 9000,
    "adaptive_gap": True, "check_fast_ms": 300,      # 不快
}
CFG_FAST = dict(CFG_SLOW, check_fast_ms=120)          # 加急


def load_speech():
    import miniaudio
    for f in sorted((ROOT / "cache" / "tts").glob("*.mp3")):
        if f.stat().st_size < 2048:
            continue
        try:
            d = miniaudio.decode_file(str(f),
                                      output_format=miniaudio.SampleFormat.FLOAT32,
                                      nchannels=1, sample_rate=SR)
            a = np.array(d.samples, dtype=np.float32)
        except Exception:
            continue
        if a.size > SR * 0.8:
            return a
    return None


def measure(cfg, audio, label):
    seg = capture.SileroSegmenter(cfg)
    calls = [0]
    orig = seg._extract

    def count(*a, **k):
        calls[0] += 1
        return orig(*a, **k)

    seg._extract = count
    block = int(SR * 30 / 1000)
    t0 = time.perf_counter()
    for i in range(0, audio.size, block):
        seg.feed(audio[i:i + block])
    dt = time.perf_counter() - t0
    dur = audio.size / SR
    print(f"  {label:16s} 音频 {dur:5.1f}s  Silero 调用 {calls[0]:4d} 次  "
          f"总耗时 {dt*1000:6.1f}ms  CPU {dt/dur*100:5.1f}%")
    return calls[0], dt


speech = load_speech()
if speech is None:
    print("没有语音样本")
    sys.exit(1)

# 构造 30 秒"打游戏"场景：大部分是噪声，中间夹几段说话
noise = (np.random.default_rng(7).standard_normal(int(SR * 30)) * 0.02).astype(np.float32)
scene = noise.copy()
pos = int(SR * 2)
for _ in range(5):
    L = min(speech.size, scene.size - pos)
    scene[pos:pos + L] = speech[:L] * 0.8 + noise[pos:pos + L]
    pos += speech.size + int(SR * 4)

print("30 秒场景（5 段语音夹在背景噪声里）\n")
c1, t1 = measure(CFG_SLOW, scene, "常规 300ms")
c2, t2 = measure(CFG_FAST, scene, "加急 120ms")

print()
print(f"调用次数 +{(c2-c1)/max(c1,1)*100:.0f}%   耗时 +{(t2-t1)/max(t1,1e-9)*100:.0f}%")
print(f"折算到单核占用：常规 {t1/30*100:.1f}%  →  加急 {t2/30*100:.1f}%")