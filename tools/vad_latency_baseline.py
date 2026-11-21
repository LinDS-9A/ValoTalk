"""测 VAD 切段延迟基线：从「人说完最后一个字」到「切段交给识别」要多久。

做法：拿一段真实语音，尾部接上不同电平的背景噪声（模拟安静/枪战），
记录 feed() 返回段落时的「说话结束后已过去时长」。

这就是端到端延迟里 VAD 贡献的那部分。
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
BLOCK_MS = 30
CFG = {
    "silero_threshold": 0.5,
    "silero_min_speech_ms": 300,
    "silero_min_silence_ms": 220,
    "silero_pad_ms": 120,
    "silero_window_s": 12.0,
    "max_utterance_ms": 9000,
    "silero_end_gap_ms": 380,
}


def load_speech() -> np.ndarray | None:
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
        if a.size > SR * 0.8 and float(np.abs(a).max()) > 0.05:
            return a
    return None


def burst_noise(sec: float, rms: float, seed: int = 0) -> np.ndarray:
    """模拟枪声：白噪声调制出的短促爆发，峰值很高但 RMS 可控。"""
    rng = np.random.default_rng(seed)
    n = int(SR * sec)
    base = rng.standard_normal(n).astype(np.float32)
    # 每 0.15s 来一次爆发
    env = np.zeros(n, dtype=np.float32)
    step = int(SR * 0.15)
    for i in range(0, n, step):
        L = min(step, n - i)
        env[i:i + L] = np.hanning(L)
    sig = base * env * 3.0
    cur = float(np.sqrt(np.mean(sig ** 2)) + 1e-12)
    return (sig * (rms / cur)).astype(np.float32)


def measure(speech: np.ndarray, tail: np.ndarray) -> float | None:
    """返回「语音结束后 → 切段」的秒数。"""
    seg = capture.SileroSegmenter(CFG)
    if not getattr(seg, "ok", False):
        return None
    audio = np.concatenate([speech, tail])
    block = int(SR * BLOCK_MS / 1000)
    speech_end_idx = speech.size

    feed_s = 0
    for i in range(0, audio.size, block):
        chunk = audio[i:i + block]
        feed_s += chunk.size / SR
        out = seg.feed(chunk)
        if out:
            # 切段发生在本次 feed 之后
            return max(0.0, feed_s - speech_end_idx / SR)
    return None


def classify_quiet(noise_rms: float) -> str:
    if noise_rms < 0.006:
        return "安静"
    if noise_rms < 0.025:
        return "一般"
    return "枪战"


def main() -> int:
    speech = load_speech()
    if speech is None:
        print("找不到语音样本（cache/tts 里没有 mp3）")
        return 1
    print(f"语音样本: {speech.size / SR:.2f}s\n")

    print("当前固定 end_gap=380ms 的表现：")
    print(f"{'背景':>8s} {'噪声RMS':>9s} {'切段延迟':>9s}")
    print("-" * 30)
    cases = [0.0, 0.004, 0.010, 0.025, 0.050, 0.080]
    rows = []
    for rms in cases:
        tail = (burst_noise(3.0, rms, seed=int(rms * 1000))
                if rms > 0 else np.zeros(int(SR * 3.0), dtype=np.float32))
        d = measure(speech, tail)
        rows.append((rms, d))
        label = "纯静音" if rms == 0 else classify_quiet(rms)
        print(f"{label:>8s} {rms:9.3f} "
              f"{(f'{d*1000:.0f} ms' if d is not None else '未切段'):>9s}")
    print()
    valid = [d for _, d in rows if d is not None]
    if valid:
        print(f"平均 {np.mean(valid)*1000:.0f} ms   最快 {min(valid)*1000:.0f} ms   "
              f"最慢 {max(valid)*1000:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())