"""验证去标题栏相关的 winapi 函数。"""
from __future__ import annotations
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk

from valotalk import winapi

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


root = tk.Tk()
root.title("测试窗口")
root.geometry("600x400+200+200")
root.update()
hwnd = winapi.top_level_hwnd(root)
print(f"hwnd = {hwnd:#x}\n")

print("=== 1) 读原始样式 ===")
winapi.user32.GetWindowLongW.argtypes = [
    ctypes.wintypes.HWND, ctypes.c_int]
winapi.user32.GetWindowLongW.restype = ctypes.c_long
style0 = winapi.user32.GetWindowLongW(
    ctypes.wintypes.HWND(hwnd), winapi.GWLP_STYLE)
print(f"  style = {style0:#010x}")
check("有 WS_CAPTION", bool(style0 & winapi.WS_CAPTION))
check("有 WS_THICKFRAME", bool(style0 & winapi.WS_THICKFRAME))

print("\n=== 2) 去标题栏 ===")
ok = winapi.strip_caption(hwnd)
root.update()
time.sleep(0.2)
style1 = winapi.user32.GetWindowLongW(
    ctypes.wintypes.HWND(hwnd), winapi.GWLP_STYLE)
print(f"  返回 {ok}  style = {style1:#010x}")
check("返回成功", ok)
check("WS_CAPTION 已去掉", not (style1 & winapi.WS_CAPTION))
check("WS_THICKFRAME 保留（能拖边框）",
      bool(style1 & winapi.WS_THICKFRAME), f"{style1:#x}")
check("WS_SYSMENU 保留（Alt+F4）",
      bool(style1 & winapi.WS_SYSMENU), f"{style1:#x}")

print("\n=== 3) 保住阴影圆角 ===")
ok2 = winapi.keep_shadow(hwnd)
print(f"  DwmExtendFrameIntoClientArea → {ok2}")
check("调用成功", ok2)

print("\n=== 4) 工作区 ===")
wa = winapi.work_area(hwnd)
print(f"  (x={wa[0]}, y={wa[1]}, w={wa[2]}, h={wa[3]})")
check("有值和尺寸", wa[2] > 0 and wa[3] > 0, str(wa))

scr_w = root.winfo_screenwidth()
scr_h = root.winfo_screenheight()
print(f"  屏幕 {scr_w}x{scr_h}，工作区高 {wa[3]}")
check("工作区不比屏幕大", wa[3] <= scr_h and wa[2] <= scr_w)

print("\n=== 5) 最大化到工作区 ===")
winapi.maximize_to_work_area(hwnd)
root.update()
time.sleep(0.3)
geo = root.geometry()
print(f"  几何 = {geo}")
# geometry 格式是 宽x高+X+Y，不是 x,y,w,h
parts = geo.replace("x", "+").split("+")
w, h = int(parts[0]), int(parts[1])
gx, gy = int(parts[2]), int(parts[3])
print(f"  解出来 宽={w} 高={h} x={gx} y={gy}")
# 去边框后实际客户区会比工作区小一圈（thickframe 边距），允许 40px
check("宽度接近工作区宽", abs(w - wa[2]) < 40, f"{w} vs {wa[2]}")
check("高度接近工作区高", abs(h - wa[3]) < 40, f"{h} vs {wa[3]}")
check("贴左上角", abs(gx - wa[0]) < 40 and abs(gy - wa[1]) < 40,
      f"({gx},{gy}) vs ({wa[0]},{wa[1]})")

print("\n=== 6) 还原样式 ===")
winapi.user32.SetWindowLongW(
    ctypes.wintypes.HWND(hwnd), winapi.GWLP_STYLE, ctypes.c_long(style0))
winapi.user32.SetWindowPos(
    ctypes.wintypes.HWND(hwnd), None, 0, 0, 0, 0,
    winapi.SWP_NOMOVE | winapi.SWP_NOSIZE | winapi.SWP_NOZORDER
    | winapi.SWP_NOACTIVATE | winapi.SWP_FRAMECHANGED)
root.update()
style2 = winapi.user32.GetWindowLongW(
    ctypes.wintypes.HWND(hwnd), winapi.GWLP_STYLE)
print(f"  恢复后 style = {style2:#010x}")
check("WS_CAPTION 回来了", bool(style2 & winapi.WS_CAPTION))

root.destroy()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)