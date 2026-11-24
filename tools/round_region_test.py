"""单独测 round_window_region，看它对窗口做了什么。"""
from __future__ import annotations
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk

from valotalk import winapi

root = tk.Tk()
root.title("圆角测试")
root.geometry("600x400+300+300")
root.update()
time.sleep(0.3)
root.update()

hwnd = winapi.top_level_hwnd(root)
print(f"hwnd = {hwnd:#x}")
print(f"初始位置 {root.winfo_rootx()},{root.winfo_rooty()} "
      f"{root.winfo_width()}x{root.winfo_height()}")
print(f"窗口状态 {root.state()}\n")

print("=== 调用 round_window_region(hwnd, 26, 1.0) ===")
t0 = time.time()
ok = winapi.round_window_region(hwnd, 26, 1.0)
print(f"  返回 {ok}  耗时 {time.time()-t0:.3f}s")

for i in range(5):
    root.update()
    time.sleep(0.1)
print(f"  之后位置 {root.winfo_rootx()},{root.winfo_rooty()} "
      f"{root.winfo_width()}x{root.winfo_height()}")
print(f"  窗口状态 {root.state()}")

print("\n=== GetWindowRect 读到的 ===")
r = ctypes.wintypes.RECT()
winapi.user32.GetWindowRect.argtypes = [
    ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
winapi.user32.GetWindowRect.restype = ctypes.wintypes.BOOL
got = winapi.user32.GetWindowRect(ctypes.wintypes.HWND(hwnd),
                                  ctypes.byref(r))
print(f"  ok={got}  rect=({r.left},{r.top})-({r.right},{r.bottom}) "
      f"={r.right-r.left}x{r.bottom-r.top}")

root.destroy()
print("\n完成")