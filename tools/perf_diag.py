"""性能诊断：ValoTalk 对帧率/游戏延迟的影响到底来自哪里。

分阶段测：
  A. 只启界面（无采集）
  B. 采集运行（无语音）
  C. 有语音进来、跑 whisper 识别
  D. 字幕重绘

每阶段测：进程 CPU、线程数、GDI/用户对象数、GPU 占用。
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.GetCurrentProcessId.restype = wintypes.DWORD
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p]
k32.GetProcessTimes.restype = wintypes.BOOL
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                       wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
user32.GetGuiResources.restype = wintypes.DWORD


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


def ft_to_int(ft: FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def proc_cpu_seconds() -> float:
    h = k32.GetCurrentProcess()
    c, e, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                        ctypes.byref(kt), ctypes.byref(ut))
    return (ft_to_int(kt) + ft_to_int(ut)) / 1e7


def mem_mb() -> tuple[float, float]:
    h = k32.GetCurrentProcess()
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(pmc)
    psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1048576, pmc.PeakWorkingSetSize / 1048576


def gdi_user_objects() -> tuple[int, int]:
    gdi = user32.GetGuiResources(k32.GetCurrentProcess(), 0)
    usr = user32.GetGuiResources(k32.GetCurrentProcess(), 1)
    return gdi, usr


def gpu_snapshot() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        txt = out.stdout.decode("gbk", "ignore").strip().splitlines()
        return txt[0] if txt else "?"
    except Exception:
        return "?"


def measure(label: str, seconds: float = 4.0) -> dict:
    t0 = proc_cpu_seconds()
    w0 = time.perf_counter()
    time.sleep(seconds)
    dt = time.perf_counter() - w0
    cpu = proc_cpu_seconds() - t0
    cur, peak = mem_mb()
    gdi, usr = gdi_user_objects()
    ncpu = ctypes.c_int()
    k32.GetSystemInfo = None  # 不用
    import os
    ncpu = os.cpu_count() or 1
    pct = cpu / dt * 100                      # 单核百分比
    total_pct = pct / ncpu                    # 占整机
    g = gpu_snapshot()
    r = {
        "label": label,
        "cpu_one_core": pct,
        "cpu_total": total_pct,
        "threads": threading.active_count(),
        "mem_mb": cur,
        "gdi": gdi,
        "usr": usr,
        "gpu": g,
    }
    print(f"{label:22s} CPU {pct:6.1f}% 单核 / {total_pct:4.1f}% 整机  "
          f"线程 {r['threads']:3d}  内存 {cur:6.1f}MB  "
          f"GDI {gdi:3d} USER {usr:3d}  GPU {g}")
    return r


def main() -> int:
    print("=" * 96)
    print("ValoTalk 性能诊断")
    print("=" * 96)
    print(f"CPU 核数 {__import__('os').cpu_count()}")
    print()

    import numpy as np
    from valotalk.app import App

    print("--- A. 启动界面（不开始采集）---")
    app = App()
    app._update_checks_off = True
    app._running = True          # 阻止 autostart 真的启动采集
    for _ in range(30):
        app.root.update()
        time.sleep(0.02)
    a = measure("A. 界面空转", 4.0)

    print("\n--- B. 启动采集（模型+麦克风+游戏音）---")
    app._running = False
    app.start()
    for _ in range(60):
        app.root.update()
        time.sleep(0.05)
    time.sleep(8)               # 等模型加载
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)
    b = measure("B. 采集运行（静音）", 5.0)

    print("\n--- C. 语音识别（whisper 推理）---")
    # 直接塞一段音频走完整识别链路
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

    t_infer = None
    infer_cpu = None
    if pcm is not None:
        c0 = proc_cpu_seconds()
        t0 = time.perf_counter()
        for _ in range(5):
            app.asr.transcribe(pcm, "en")
        t_infer = (time.perf_counter() - t0) / 5
        infer_cpu = (proc_cpu_seconds() - c0) / 5
        print(f"  单次识别（{pcm.size/16000:.2f}s 音频）：{t_infer*1000:.0f}ms  "
              f"CPU {infer_cpu*100:.0f}% 单核·秒")
    c = measure("C. 识别后静置", 4.0)

    print("\n--- D. 字幕满屏重绘 ---")
    import time as _t
    for i in range(6):
        app.overlay.add("队友", f"Enemy spotted on A site, watch the flank. #{i}",
                        "敌人在A点，注意绕后", 60)
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)
    # 强制连续重绘 200 次看单次成本
    c0 = proc_cpu_seconds()
    t0 = time.perf_counter()
    for _ in range(200):
        app.overlay._render()
    redraw_ms = (time.perf_counter() - t0) / 200 * 1000
    redraw_cpu = (proc_cpu_seconds() - c0) / 200 * 100
    print(f"  单次重绘（6 条满屏）：{redraw_ms:.2f}ms  CPU {redraw_cpu:.2f}% 单核·秒")
    d = measure("D. 有字幕静置", 4.0)

    print("\n" + "=" * 96)
    print("结论")
    print("=" * 96)
    print(f"  空闲基线（A）      {a['cpu_one_core']:.1f}% 单核")
    print(f"  采集+模型（B）     {b['cpu_one_core']:.1f}% 单核")
    print(f"  有字幕（D）        {d['cpu_one_core']:.1f}% 单核")
    print(f"  内存                {d['mem_mb']:.0f} MB")
    print(f"  GDI/USER 对象       {d['gdi']} / {d['usr']}")
    if t_infer:
        print(f"  单次语音识别        {t_infer*1000:.0f} ms（这段时间 CPU 满打一个核）")
    print(f"  单次字幕重绘        {redraw_ms:.2f} ms")

    try:
        app.shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())