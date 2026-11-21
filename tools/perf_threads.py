"""按线程拆 CPU：找出 App 里到底哪个线程在烧。

用 GetThreadTimes 对每个线程单独计时，跑 10 秒后按占用率排序。
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

THREAD_QUERY_INFORMATION = 0x0040
TH32CS_SNAPTHREAD = 0x00000004


class FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.GetCurrentProcessId.restype = wintypes.DWORD
k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenThread.restype = wintypes.HANDLE
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.GetThreadTimes.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                               ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_void_p]
k32.GetThreadTimes.restype = wintypes.BOOL
k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]


def ft_seconds(ft) -> float:
    return ((ft.hi << 32) | ft.lo) / 1e7


def thread_cpu(tid: int) -> float | None:
    h = k32.OpenThread(THREAD_QUERY_INFORMATION, False, tid)
    if not h:
        return None
    try:
        a, b, c, d = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if not k32.GetThreadTimes(h, ctypes.byref(a), ctypes.byref(b),
                                  ctypes.byref(c), ctypes.byref(d)):
            return None
        return ft_seconds(c) + ft_seconds(d)
    finally:
        k32.CloseHandle(h)


def list_threads(pid: int) -> list[int]:
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return []
    out = []
    try:
        te = THREADENTRY32()
        te.dwSize = ctypes.sizeof(THREADENTRY32)
        ok = k32.Thread32First(snap, ctypes.byref(te))
        while ok:
            if te.th32OwnerProcessID == pid:
                out.append(int(te.th32ThreadID))
            ok = k32.Thread32Next(snap, ctypes.byref(te))
    finally:
        k32.CloseHandle(snap)
    return out


def main() -> int:
    from valotalk.app import App

    pid = int(k32.GetCurrentProcessId())
    app = App()
    app._running = True
    for _ in range(30):
        app.root.update()
        time.sleep(0.02)

    print("启动采集 …")
    app._running = False
    app.start()
    for _ in range(40):
        app.root.update()
        time.sleep(0.05)
    time.sleep(8)                        # 等模型
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)

    # 记录 python 线程名
    names = {t.ident: t.name for t in __import__("threading").enumerate()}

    before = {}
    for tid in list_threads(pid):
        c = thread_cpu(tid)
        if c is not None:
            before[tid] = c

    DUR = 10.0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < DUR:
        app.root.update()
        time.sleep(0.02)
    elapsed = time.perf_counter() - t0

    after = {}
    for tid in list_threads(pid):
        c = thread_cpu(tid)
        if c is not None:
            after[tid] = c

    rows = []
    total = 0.0
    for tid, c1 in before.items():
        c2 = after.get(tid)
        if c2 is None:
            continue
        d = c2 - c1
        total += d
        if d > 0.005:
            rows.append((d / elapsed * 100, tid, names.get(tid, "?")))

    rows.sort(reverse=True)
    print(f"\n{'线程':<22s}{'TID':>8s}{'单核CPU':>10s}   占比")
    print("-" * 62)
    for pct, tid, name in rows:
        share = pct / max(total / elapsed * 100, 1e-9) * 100
        print(f"{name:<22s}{tid:>8d}{pct:9.1f}%{share:8.0f}%")
    print("-" * 62)
    print(f"{'合计':<22s}{'':>8s}{total / elapsed * 100:9.1f}%")
    print(f"\n线程总数 {len(after)}")

    app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())