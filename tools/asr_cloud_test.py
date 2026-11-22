"""验证 CloudASR 类：预热 + 识别 + 延迟 + 失败处理。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.asr_cloud import CloudASR, fix_ja_terms
from valotalk.config import CONFIG

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


asr = CloudASR(CONFIG.get, log=print)
print(f"API key: {'有' if asr.available() else '没有'}")
print(f"模型: {asr.model}\n")

check("有 API key", asr.available())

print("=== 1) 预热 ===")
t0 = time.time()
ok = asr.warmup()
print(f"  预热 {'成功' if ok else '失败'} {time.time()-t0:.2f}s  {asr.last_error}")
check("预热成功", ok, asr.last_error)

print("\n=== 2) 真实日语识别 ===")
import asyncio
import edge_tts
import miniaudio

ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "cache" / "_cloud_test.mp3"


async def gen(text):
    c = edge_tts.Communicate(text, "ja-JP-KeitaNeural")
    await c.save(str(out))


CASES = [
    ("Aサイトに敵、フランクに注意。", ["サイト", "敵", "フランク"]),
    ("ウルト使うから、カバーして。", ["ウルト"]),
    ("残りHP少ない、詰めて。", ["HP"]),
]

for text, keywords in CASES:
    asyncio.run(gen(text))
    dec = miniaudio.decode_file(str(out),
                                output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=1, sample_rate=16000)
    a = np.array(dec.samples, dtype=np.float32)

    times = []
    result = ""
    for _ in range(3):
        t0 = time.time()
        result = asr.transcribe(a, "ja")
        times.append(time.time() - t0)

    print(f"\n  原文: {text}  ({a.size/16000:.2f}s)")
    print(f"  识别: {result!r}")
    if asr.last_error:
        print(f"  ⚠ 错误: {asr.last_error}")
    print(f"  延迟: " + "  ".join(f"{t*1000:.0f}ms" for t in times))
    # CloudASR 只负责识别；术语纠正由 app 层做（本地识别也走同一套纠正）
    fixed = fix_ja_terms(result)
    if fixed != result:
        print(f"  〔纠错〕→ {fixed!r}")
    hit = sum(1 for k in keywords if k.lower() in fixed.lower())
    check(f"识别+纠错后命中 {hit}/{len(keywords)} 个关键词",
          hit >= max(1, len(keywords) - 1),
          f"{fixed!r} err={asr.last_error}")
    check("复用后延迟 < 1.5s", min(times) < 1.5, f"min={min(times)*1000:.0f}ms")

out.unlink(missing_ok=True)

print("\n=== 3) 空音频 / 短音频 ===")
check("空音频返回空串", asr.transcribe(np.zeros(0, dtype=np.float32), "ja") == "")
check("超短音频返回空串",
      asr.transcribe(np.zeros(800, dtype=np.float32), "ja") == "")

print("\n=== 4) 没有 key 时优雅失败 ===")
bad = CloudASR(lambda k, d=None: "", log=lambda *_: None)
check("available() 返回 False", not bad.available())
check("transcribe 返回空串",
      bad.transcribe(np.zeros(16000, dtype=np.float32), "ja") == "")
check("有错误信息", bool(bad.last_error), bad.last_error)

asr.close()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)