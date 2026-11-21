"""归因：117% 单核到底花在哪。

逐项打开，单独测每一项的 CPU：
  1. soundcard 采集（回调空转）
  2. 回调里做 resample + peak（真实路径）
  3. + Silero VAD（每 300ms）
  4. 只留 1 路采集
  5. tkinter 泵单独测（主线程）
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk import capture

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p]
k32.GetProcessTimes.restype = wintypes.BOOL


class FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


def cpu_seconds() -> float:
    """进程累计 CPU 秒数。FILETIME 单位是 100ns，必须除以 1e7。"""
    h = k32.GetCurrentProcess()
    a, b, c, d = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    k32.GetProcessTimes(h, ctypes.byref(a), ctypes.byref(b),
                        ctypes.byref(c), ctypes.byref(d))
    ticks = ((c.hi << 32) | c.lo) + ((d.hi << 32) | d.lo)
    return ticks / 1e7


def measure(sec: float = 4.0) -> float:
    t0 = cpu_seconds()
    w0 = time.perf_counter()
    time.sleep(sec)
    dt = time.perf_counter() - w0
    return (cpu_seconds() - t0) / dt * 100


SR = 48000
BLOCK_MS = 30
GAME_DEV = "扬声器 (MCHOSE V9 PRO)"
MIC_DEV = "Mic (MCHOSE V9 PRO)"

print(f"CPU 核数 {os.cpu_count()}")
print(f"块速率：2 路 × {1000/BLOCK_MS:.0f}/秒 = {2*1000/BLOCK_MS:.0f} 块/秒\n")
print(f"{'阶段':<34s}{'单核CPU':>10s}")
print("-" * 46)

base = measure(3)
print(f"{'0. 基线（什么都不开）':<34s}{base:9.1f}%")

chunks = {"n": 0}


def noop(_arr):
    chunks["n"] += 1


src1 = capture.AudioSource(GAME_DEV, True, SR, BLOCK_MS, noop, label="g")
src2 = capture.AudioSource(MIC_DEV, False, SR, BLOCK_MS, noop, label="m")
src1.start()
src2.start()
time.sleep(2)
n0 = chunks["n"]
t_cap = measure(4)
rate = (chunks["n"] - n0) / 4
print(f"{'1. 两路采集（回调空转）':<34s}{t_cap:9.1f}%")
print(f"   {'':34s}  实收 {rate:.0f} 块/秒")


def work(arr):
    _ = float(np.max(np.abs(arr)))
    capture.resample(arr, SR, capture.TARGET_SR)


src1.on_chunk = work
src2.on_chunk = work
time.sleep(1)
t_work = measure(4)
print(f"{'2. + resample/peak（真实路径）':<34s}{t_work:9.1f}%")

seg = capture.SileroSegmenter({"adaptive_gap": True})
t_vad = None
if getattr(seg, "ok", False):
    def vad_cb(arr):
        seg.feed(capture.resample(arr, SR, capture.TARGET_SR))

    src1.on_chunk = vad_cb
    src2.on_chunk = vad_cb
    time.sleep(1)
    t_vad = measure(5)
    print(f"{'3. + Silero VAD':<34s}{t_vad:9.1f}%")
else:
    print(f"{'3. Silero 不可用':<34s}{'-':>10s}")

src2.stop()
time.sleep(0.5)
t_one = measure(4)
print(f"{'4. 只留 1 路采集':<34s}{t_one:9.1f}%")

src1.stop()
time.sleep(0.5)
t_off = measure(2)
print(f"{'5. 全部关掉':<34s}{t_off:9.1f}%")

print("-" * 46)
print(f"\n净增量：")
print(f"  采集本身     {t_cap - base:+.1f}% 单核")
print(f"  resample     {t_work - t_cap:+.1f}% 单核")
if t_vad is not None:
    print(f"  Silero VAD   {t_vad - t_work:+.1f}% 单核")
print(f"  两路→一路    {t_one - t_vad:+.1f}% 单核（省下的是第二路）")