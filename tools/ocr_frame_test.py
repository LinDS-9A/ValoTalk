"""最坏情况验证：OCR 和「游戏」同优先级时会不会掉帧。

真实情况里 ValoTalk 是 Below Normal，游戏优先拿 CPU，比这个更安全。
这里故意都设成 Normal（=没有降级保护），如果连这都不卡，那实际更不会卡。

「游戏」用一个 busy 线程模拟：每帧要干 10ms 的活（≈60fps 下 60% 负载），
统计它有没有错过帧。
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_case(threads: int, cores: int, with_ocr: bool) -> dict:
    code = f'''
import ctypes, ctypes.wintypes as wintypes, json, sys, threading, time
sys.path.insert(0, r"{ROOT}")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]

# 限制核心数
mask = (1 << {cores}) - 1
k32.SetProcessAffinityMask(k32.GetCurrentProcess(), mask)
# ★ 故意设 Normal（最坏情况，ValoTalk 实际是 Below Normal）
k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00000020)

from valotalk.config import CONFIG
from valotalk.ocr import ChatOCR

ocr = ChatOCR(CONFIG.get)
ocr.set_threads({threads})
img = ocr.grab(CONFIG.get("ocr.region", [0,0,0,0]))
if img is None:
    print(json.dumps({{"error": ocr.last_error}})); sys.exit(1)
ocr.read_lines(img)      # 预热

# ---- 模拟游戏渲染：每帧 16.67ms 预算，干 10ms 的活 ----
FRAME = 1/60
WORK = 0.010             # 每帧计算 10ms
frame_times = []         # 每帧实际花的时间
frame_gaps = []          # 相邻帧开始时刻的间隔
stop = threading.Event()

def workload(sec):
    end = time.perf_counter() + sec
    x = 0.0
    while time.perf_counter() < end:
        x = x * 1.000001 + 0.5

def game_thread():
    next_t = time.perf_counter()
    prev_start = next_t
    while not stop.is_set():
        start = time.perf_counter()
        frame_gaps.append(start - prev_start)
        prev_start = start
        workload(WORK)
        frame_times.append(time.perf_counter() - start)
        next_t += FRAME
        now = time.perf_counter()
        if next_t > now:
            time.sleep(next_t - now)
        else:
            next_t = now      # 追不上就重新对齐（掉帧）

th = threading.Thread(target=game_thread, daemon=True)
th.start()
time.sleep(0.6)

n_ocr = 0
if {with_ocr}:
    t0 = time.perf_counter()
    ocr.read_lines(img)
    n_ocr = 1
    # 连跑几次模拟连续来消息
    for _ in range(2):
        ocr.read_lines(img)
        n_ocr += 1
    ocr_dur = (time.perf_counter() - t0) / n_ocr
else:
    ocr_dur = 0
    time.sleep(0.8)

time.sleep(0.6)
stop.set(); th.join(timeout=2)

gaps = [g*1000 for g in frame_gaps[10:]]
times = [t*1000 for t in frame_times[10:]]
over = [g for g in gaps if g > FRAME*1000*1.5]      # 超过 1.5 帧
missed = sum(max(0, round(g/(FRAME*1000)) - 1) for g in gaps)

print(json.dumps({{
    "threads": {threads}, "cores": {cores}, "with_ocr": {with_ocr},
    "frames": len(gaps),
    "ocr_ms": ocr_dur*1000,
    "gap_med": sorted(gaps)[len(gaps)//2] if gaps else 0,
    "gap_max": max(gaps) if gaps else 0,
    "work_max": max(times) if times else 0,
    "over_1_5x": len(over),
    "missed_frames": missed,
}}))
'''
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                          capture_output=True, timeout=600,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (proc.stdout or b"").decode("utf-8", "ignore")
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return {"error": (proc.stderr or b"").decode("utf-8", "ignore")[-200:]}


def main() -> int:
    print("最坏情况：OCR 与「游戏」同为 Normal 优先级")
    print("「游戏」每帧 16.67ms 里要干 10ms 的活（60% 负载）\n")
    print(f"{'核心':>4s}{'线程':>5s}{'OCR':>5s}{'帧间隔中位':>11s}"
          f"{'最长间隔':>9s}{'超1.5帧':>8s}{'丢帧总数':>8s}")
    print("-" * 56)

    for cores in (4, 6, 8, 24):
        # 基线：不开 OCR
        b = run_case(1, cores, False)
        if "error" in b:
            print(f"{cores:4d} 基线 ERROR {b['error'][:40]}")
            continue
        print(f"{cores:4d}{'—':>5s}{'关':>5s}{b['gap_med']:10.1f}ms"
              f"{b['gap_max']:8.1f}ms{b['over_1_5x']:8d}{b['missed_frames']:8d}")

        for threads in (1, 2, 4):
            if threads > cores:
                continue
            d = run_case(threads, cores, True)
            if "error" in d:
                print(f"{cores:4d}{threads:5d}  ERROR {d['error'][:40]}")
                continue
            print(f"{cores:4d}{threads:5d}{d['ocr_ms']:4.0f}ms"
                  f"{d['gap_med']:10.1f}ms{d['gap_max']:8.1f}ms"
                  f"{d['over_1_5x']:8d}{d['missed_frames']:8d}")

    print("\n" + "=" * 56)
    print("判定：超过 1.5 帧（25ms）的间隔越多，越可能被察觉")
    print("      ValoTalk 实际是 Below Normal 优先级，会比这更好")
    return 0


if __name__ == "__main__":
    sys.exit(main())