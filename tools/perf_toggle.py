"""逐项关闭 App 组件，看 CPU 掉多少 —— 找出那个 20% 的无名线程。"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import time
from pathlib import Path

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


def measure(sec=4.0) -> float:
    t0 = cpu_seconds()
    w0 = time.perf_counter()
    end = w0 + sec
    while time.perf_counter() < end:
        if APP is not None:
            try:
                APP.root.update()
            except Exception:
                pass
        time.sleep(0.02)
    return (cpu_seconds() - t0) / (time.perf_counter() - w0) * 100


APP = None


def main() -> int:
    global APP
    from valotalk.app import App

    app = App()
    APP = app
    app._running = True
    for _ in range(30):
        app.root.update()
        time.sleep(0.02)

    app._running = False
    app.start()
    for _ in range(40):
        app.root.update()
        time.sleep(0.05)
    time.sleep(8)
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)

    print(f"{'状态':<30s}{'单核CPU':>10s}")
    print("-" * 42)
    full = measure(5)
    print(f"{'全部开启':<30s}{full:9.1f}%")

    # 1) 关 OCR
    print(f"\n  OCR 间隔配置: {app._get('ocr.interval_ms')} ms")
    app.flags["chat"] = False
    app._chat_stop.set()
    t = measure(4)
    print(f"{'关掉聊天 OCR':<30s}{t:9.1f}%   ({t-full:+.1f})")
    app.flags["chat"] = True
    app._chat_stop.clear()
    app._start_chat_loop()
    time.sleep(1)

    # 2) 关手机遥控
    app.remote.stop()
    t2 = measure(4)
    print(f"{'关掉手机遥控':<30s}{t2:9.1f}%   ({t2-t:+.1f})")
    app.remote.start()

    # 3) 关热键
    app.hotkeys.stop()
    t3 = measure(4)
    print(f"{'关掉热键轮询':<30s}{t3:9.1f}%   ({t3-t2:+.1f})")
    app._bind_hotkeys()
    time.sleep(1)

    # 4) 关 overlay 循环
    try:
        app.overlay.win.withdraw()
    except Exception:
        pass
    t4 = measure(4)
    print(f"{'隐藏字幕窗':<30s}{t4:9.1f}%   ({t4-t3:+.1f})")
    try:
        app.overlay.win.deiconify()
    except Exception:
        pass

    # 5) 两个都关（OCR + 手机）
    app.flags["chat"] = False
    app._chat_stop.set()
    app.remote.stop()
    t5 = measure(4)
    print(f"{'OCR + 手机都关':<30s}{t5:9.1f}%   ({t5-t3:+.1f})")

    print("\n" + "=" * 42)
    print(f"基线全开 {full:.1f}% → 关 OCR+手机 {t5:.1f}%")
    print(f"这两项合计约 {full - t5:.1f}% 单核")

    app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())