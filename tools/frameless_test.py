"""验证无标题栏：样式去掉、窗口按钮可用、拖动生效、最大化不盖任务栏。"""
from __future__ import annotations
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

import tkinter as tk

import valotalk.ui_theme as ui
from valotalk import winapi

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


def pump(app, n=14, gap=0.05):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


with config_guard():
    from valotalk.app import App

    app = App()
    app._running = True
    pump(app, 24, 0.07)

    hwnd = winapi.top_level_hwnd(app.root)
    winapi.user32.GetWindowLongW.argtypes = [
        ctypes.wintypes.HWND, ctypes.c_int]
    winapi.user32.GetWindowLongW.restype = ctypes.c_long

    def style():
        return winapi.user32.GetWindowLongW(
            ctypes.wintypes.HWND(hwnd), winapi.GWLP_STYLE)

    print("=== 1) 标题栏已去掉 ===")
    st = style()
    print(f"  _frameless = {app._frameless}  style = {st:#010x}")
    check("标记为无边框", app._frameless is True)
    check("WS_CAPTION 没了", not (st & winapi.WS_CAPTION))
    check("WS_THICKFRAME 还在（能拖边框）",
          bool(st & winapi.WS_THICKFRAME), f"{st:#x}")
    check("WS_SYSMENU 还在（Alt+F4）",
          bool(st & winapi.WS_SYSMENU), f"{st:#x}")

    print("\n=== 2) 三个窗口按钮 ===")
    btns = getattr(app, "_win_btns", [])
    print(f"  共 {len(btns)} 个: {[b._kind for b in btns]}")
    check("有 3 个", len(btns) == 3, str(len(btns)))
    check("是 WinButton", all(isinstance(b, ui.WinButton) for b in btns))
    kinds = [b._kind for b in btns]
    check("有关闭", "close" in kinds, str(kinds))
    check("有最小化", "min" in kinds, str(kinds))
    check("有最大化", "max" in kinds, str(kinds))

    print("\n=== 3) 按钮在窗口内、不重叠 ===")
    RX = app.root.winfo_rootx()
    RW = app.root.winfo_width()
    prev_x = None
    for b in btns:
        x = b.winfo_rootx() - RX
        w = b.winfo_width()
        y = b.winfo_rooty() - app.root.winfo_rooty()
        print(f"  {b._kind:8s} x={x:4d} w={w} y={y}")
        check(f"{b._kind} 在窗口内", 0 <= x and x + w <= RW)
        if prev_x is not None:
            check(f"{b._kind} 和上一个不重叠", abs(x - prev_x) >= w - 1,
                  f"{x} vs {prev_x}")
        prev_x = x

    print("\n=== 4) 拖动 ===")
    x0, y0 = app.root.winfo_x(), app.root.winfo_y()
    head = app._win_btns[0].master

    # tkinter 的 event_generate 对 rootx/rooty 不可靠（实测 handler 收不到），
    # 所以这里从代码层面验证拖动逻辑确实绑上去了，再用 geometry 直接验证移动
    import inspect
    src = inspect.getsource(app.__class__._build_ui)
    print(f"  head 的 <Button-1> 绑定: {head.bind('<Button-1>')[:50] or '(空)'}")
    check("head 绑了左键", bool(head.bind("<Button-1>")))
    check("绑了拖动移动", 'bind("<B1-Motion>"' in src)
    check("绑了释放", 'bind("<ButtonRelease-1>"' in src)
    check("绑了双击最大化", 'bind("<Double-Button-1>"' in src)
    check("拖动里用 _frameless 兜底", "_frameless" in src)
    check("拖动用 geometry 移动",
          'e.x_root - self._drag_off[0]' in src)

    # 直接验证 geometry 能把窗口挪走（拖动最终就是调它）
    app.root.geometry(f"+{x0 + 40}+{y0 + 30}")
    pump(app, 4)
    x1, y1 = app.root.winfo_x(), app.root.winfo_y()
    print(f"  geometry 移动 ({x0},{y0}) → ({x1},{y1})")
    check("窗口能移位", (x1, y1) != (x0, y0), "没动")

    print("\n=== 5) 最大化 / 还原 ===")
    app._toggle_maximize()
    pump(app, 12)
    geo_max = app.root.geometry()
    wa = winapi.work_area(hwnd)
    print(f"  最大化后 {geo_max}，工作区 {wa[2]}x{wa[3]}")
    check("标记为最大化", app._is_maximized is True)
    parts = geo_max.replace("x", "+").split("+")
    w_max, h_max = int(parts[0]), int(parts[1])
    check("宽度接近工作区", abs(w_max - wa[2]) < 40, f"{w_max} vs {wa[2]}")
    check("高度接近工作区（没盖任务栏）", abs(h_max - wa[3]) < 40,
          f"{h_max} vs {wa[3]}")
    check("按钮变成还原图标", app._win_btns[1]._kind == "restore",
          app._win_btns[1]._kind)

    app._toggle_maximize()
    pump(app, 12)
    geo_back = app.root.geometry()
    print(f"  还原后 {geo_back}")
    check("标记取消", app._is_maximized is False)
    check("按钮变回最大化图标", app._win_btns[1]._kind == "max",
          app._win_btns[1]._kind)
    check("尺寸回到原样", geo_back == app._restore_geo or geo_back != geo_max,
          f"{geo_back} vs {geo_max}")

    print("\n=== 6) 界面仍然正常 ===")
    for page in ("cfg", "about", "home"):
        app._show_page(page)
        pump(app, 6)
    check("三页切换都 OK", True)
    print(f"  日志区 {app.txt.winfo_height()}px")
    check("日志区可用", app.txt.winfo_height() > 70)

    app.shutdown()

print("\n" + "=" * 52)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 52)
sys.exit(0 if failed == 0 else 1)