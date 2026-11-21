"""稳态测量：各种真实场景下 ValoTalk 抢走多少 CPU / GPU。

场景：
  1. 刚启动（聊天 OCR 全速）
  2. 长时间无聊天消息（空闲退避生效）
  3. 队友说话走完整链路
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p]


class FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


def cpu_seconds() -> float:
    h = k32.GetCurrentProcess()
    a, b, c, d = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    k32.GetProcessTimes(h, ctypes.byref(a), ctypes.byref(b),
                        ctypes.byref(c), ctypes.byref(d))
    return (((c.hi << 32) | c.lo) + ((d.hi << 32) | d.lo)) / 1e7


APP = None


def measure(sec=6.0) -> float:
    t0 = cpu_seconds()
    w0 = time.perf_counter()
    end = w0 + sec
    while time.perf_counter() < end:
        try:
            APP.root.update()
        except Exception:
            pass
        time.sleep(0.02)
    return (cpu_seconds() - t0) / (time.perf_counter() - w0) * 100


def gpu() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.decode("gbk", "ignore").strip().splitlines()[0]
    except Exception:
        return "?"


def main() -> int:
    global APP
    from valotalk.app import App

    ncpu = os.cpu_count() or 1
    print(f"CPU {ncpu} 核\n")
    print(f"{'场景':<30s}{'单核':>8s}{'整机':>8s}   GPU")
    print("-" * 60)

    before = gpu()
    app = App()
    APP = app
    app._running = True
    for _ in range(30):
        app.root.update()
        time.sleep(0.02)
    a = measure(4)
    print(f"{'0. 只开面板':<30s}{a:7.1f}%{a/ncpu:7.2f}%   {before}")

    app._running = False
    app.start()
    for _ in range(50):
        app.root.update()
        time.sleep(0.05)
    time.sleep(9)
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)

    b = measure(6)
    print(f"{'1. 刚开（OCR 全速）':<30s}{b:7.1f}%{b/ncpu:7.2f}%   {gpu()}")

    # 等空闲退避生效
    print("   等 40 秒让空闲退避生效 …")
    t0 = time.time()
    while time.time() - t0 < 40:
        app.root.update()
        time.sleep(0.03)

    c = measure(8)
    print(f"{'2. 长时间没聊天消息（稳态）':<30s}{c:7.1f}%{c/ncpu:7.2f}%   {gpu()}")

    # 队友说话
    import miniaudio
    ROOT = Path(__file__).resolve().parent.parent
    pcm = None
    for f in sorted((ROOT / "cache" / "tts").glob("*.mp3")):
        if f.stat().st_size < 2048:
            continue
        try:
            d = miniaudio.decode_file(str(f),
                                      output_format=miniaudio.SampleFormat.FLOAT32,
                                      nchannels=1, sample_rate=16000)
            arr = np.array(d.samples, dtype=np.float32)
            if arr.size > 16000:
                pcm = arr
                break
        except Exception:
            continue

    if pcm is not None:
        t0 = time.perf_counter()
        c0 = cpu_seconds()
        for _ in range(10):
            app.asr.transcribe(pcm, "en")
        dt = time.perf_counter() - t0
        cpu = cpu_seconds() - c0
        print(f"   单次识别 {dt/10*1000:.0f}ms，CPU {cpu/10*1000:.0f}ms")

    d = measure(6)
    print(f"{'3. 有语音进来之后':<30s}{d:7.1f}%{d/ncpu:7.2f}%   {gpu()}")

    print("-" * 60)
    print(f"\n稳态占用：{c:.1f}% 单核 = 整机 {c/ncpu:.2f}%")
    print(f"（{ncpu} 核里占 {(c/ncpu):.2f}%，游戏还有 {(100-c/ncpu):.1f}% 可用）")

    app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())