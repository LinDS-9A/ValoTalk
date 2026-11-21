"""自适应静音判定：延迟 + 完整性 + 稳定性验证。

只测延迟不够 —— 等待时间变短后有可能把话切断（丢字）。
所以每个场景同时检查：
  1. 切段延迟（说完到切出来多久）
  2. 切出的音频是否覆盖了原始语音（丢字检查）
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk import capture

ROOT = Path(__file__).resolve().parent.parent
SR = 16000
BLOCK_MS = 30

BASE_CFG = {
    "silero_threshold": 0.5,
    "silero_min_speech_ms": 300,
    "silero_min_silence_ms": 220,
    "silero_pad_ms": 120,
    "silero_window_s": 12.0,
    "max_utterance_ms": 9000,
}
ADAPT = dict(BASE_CFG, adaptive_gap=True)
FIXED = dict(BASE_CFG, adaptive_gap=False, silero_end_gap_ms=380)

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"    [PASS] {name}")
    else:
        print(f"    [FAIL] {name} {extra}")
        failed += 1


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


def run(seg, speech, tail, lead=np.zeros(0, dtype=np.float32)):
    """返回 (切段延迟秒, 切出的语音秒数)。"""
    audio = np.concatenate([lead, speech, tail])
    block = int(SR * BLOCK_MS / 1000)
    speech_end = lead.size + speech.size
    feed_s = 0.0
    for i in range(0, audio.size, block):
        chunk = audio[i:i + block]
        feed_s += chunk.size / SR
        out = seg.feed(chunk)
        if out:
            seg_s = out[0].size / SR
            return max(0.0, feed_s - speech_end / SR), seg_s
    return None, 0.0


def main() -> int:
    speech = load_speech()
    if speech is None:
        print("没有语音样本")
        return 1
    sp_s = speech.size / SR
    print(f"语音样本 {sp_s:.2f}s，采样 {SR}Hz\n")

    # 前置 1.5s 背景音，让噪声估计先收敛（更接近真实打游戏时的情况）
    scenarios = [
        ("纯静音", 0.0),
        ("安静",   0.004),
        ("一般",   0.015),
        ("枪战",   0.050),
        ("爆音",   0.080),
    ]

    for label, rms in scenarios:
        print(f"=== {label}（噪声 RMS {rms}）===")
        lead = (burst_noise(1.5, rms, seed=1) if rms > 0
                else np.zeros(int(SR * 1.5), dtype=np.float32))
        tail = (burst_noise(3.0, rms, seed=2) if rms > 0
                else np.zeros(int(SR * 3.0), dtype=np.float32))

        seg_f = capture.SileroSegmenter(FIXED)
        seg_a = capture.SileroSegmenter(ADAPT)
        if not seg_f.ok or not seg_a.ok:
            print("  Silero 不可用")
            return 1

        d_fix, s_fix = run(seg_f, speech, tail, lead)
        d_ad, s_ad = run(seg_a, speech, tail, lead)

        st = seg_a.stats
        print(f"    固定: {d_fix*1000:4.0f}ms  切出 {s_fix:.2f}s")
        print(f"    自适应: {d_ad*1000:4.0f}ms  切出 {s_ad:.2f}s  "
              f"(噪声估 {st['noise_rms']:.4f}, 等 {st['gap_ms']}ms)")

        # 完整性：切出的音频不能比原语音短太多（允许 pad 造成的少量出入）
        check(f"不丢字（切出 ≥ 原语音 85%）",
              s_ad >= sp_s * 0.85, f"{s_ad:.2f}s vs {sp_s:.2f}s")
        # 也不应该长太多（否则把背景噪声吞进来了）
        check(f"不吞噪声（切出 ≤ 原语音 2.2 倍）",
              s_ad <= sp_s * 2.2, f"{s_ad:.2f}s vs {sp_s:.2f}s")

        # 安静场景必须更快
        if rms <= 0.004:
            check("安静时比固定阈值更快",
                  d_ad is not None and d_fix is not None and d_ad < d_fix - 0.10,
                  f"{d_ad*1000:.0f} vs {d_fix*1000:.0f} ms")
        print()

    print("=== 噪声突变：等待时长是否平滑 ===")
    seg = capture.SileroSegmenter(ADAPT)
    gaps = []
    gap_max_step = ADAPT.get("gap_max_step_ms", 60)
    # 每段 2.5s：噪声估计用最近 0.8s，时间太短的话窗口里还是上一段的声音
    PHASE_S = 2.5
    for phase, rms in [("安静", 0.004), ("突然枪战", 0.080), ("安静下来", 0.004)]:
        audio = burst_noise(PHASE_S, rms, seed=3) if rms > 0 else \
            np.zeros(int(SR * PHASE_S), dtype=np.float32)
        block = int(SR * 30 / 1000)
        for i in range(0, audio.size, block):
            seg.feed(audio[i:i + block])
        gaps.append(seg.cur_gap_s * 1000)
        print(f"    {phase:10s} → 等待 {gaps[-1]:.0f}ms  "
              f"(噪声估 {seg.noise_rms:.4f})")

    # 1 秒内大约 3 次更新，每次最多 gap_max_step，所以单步上限 ≈ 3*step
    limit = gap_max_step * 4
    steps = [abs(gaps[i + 1] - gaps[i]) for i in range(len(gaps) - 1)]
    check(f"等待时长平滑（单步 < {limit}ms）",
          all(s < limit for s in steps), f"steps={[round(s) for s in steps]}")
    check("枪战结束后等待时长回落",
          gaps[-1] < gaps[-2], f"{gaps[-1]:.0f} vs {gaps[-2]:.0f} ms")

    print("\n" + "=" * 52)
    print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
    print("=" * 52)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())