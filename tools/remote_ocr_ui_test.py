"""验证 OCR 速度档 + 手机遥控（已在功能开关区）。"""
from __future__ import annotations
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App
from valotalk.ocr import ChatOCR

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


def pump(app, n=12, gap=0.05):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


app = App()
app._running = True
pump(app, 20, 0.08)

print("=== 1) OCR 速度档：三档文字 ===")
choices = ChatOCR.SPEED_CHOICES
for n in sorted(choices):
    print(f"  {n} → {choices[n]}")
check("有 3 个档位", len(choices) == 3)
check("1 线程 829ms", "829" in choices.get(1, ""))
check("2 线程 650ms", "650" in choices.get(2, ""))
check("4 线程 625ms", "625" in choices.get(4, ""))

print("\n=== 2) 下拉框 ===")
labels = list(app.cb_ocr_speed._values)
print(f"  选项: {labels}")
print(f"  当前: {app.cb_ocr_speed.get()}")
check("3 项", len(labels) == 3)
check("默认 650ms 档", "650" in app.cb_ocr_speed.get())

print("\n=== 3) 提示文字 ===")
hint = app.spd_hint.cget("text")
print(f"  {hint}")
check("提示速度/CPU 权衡", "快" in hint and "CPU" in hint)

print("\n=== 4) 切档 ===")
for n in (4, 1, 2):
    app.cb_ocr_speed.set(choices[n])
    app._on_ocr_speed_change()
    pump(app, 4)
    ok = (int(app._get("ocr.onnx_threads")) == n and app.ocr.threads() == n)
    check(f"切到 {n} 线程生效", ok,
          f"config={app._get('ocr.onnx_threads')} ocr={app.ocr.threads()}")

print("\n=== 5) 手机遥控在功能开关区（同一行）===")
check("有 v_remote 变量", hasattr(app, "v_remote"))
check("有 chk_remote 开关行", hasattr(app, "chk_remote"))
check("地址标签在开关行的 extra 区",
      app.remote_lbl.master is app.chk_remote.extra)
check("二维码按钮也在 extra 区",
      app.btn_remote_qr.master is app.chk_remote.extra)
# 强制回到关闭态
app._set("remote.enabled", False)
app.remote.stop()
app.v_remote.set(False)
app._set_remote_ui(False)
pump(app, 8)

print(f"  初始: 开关={app.v_remote.get()} 地址={app.remote_lbl.cget('text')!r}")
check("默认关闭", app.v_remote.get() is False)
check("地址显示未开启", app.remote_lbl.cget("text") == "未开启",
      app.remote_lbl.cget("text"))
check("服务未启动", app.remote._srv is None)
check("关着时二维码隐藏", not app.btn_remote_qr.winfo_manager())

print("\n=== 6) 开关打开 ===")
app.v_remote.set(True)
app._on_remote_toggle()
pump(app, 32, 0.06)
check("config 为真", app._get("remote.enabled") is True)
check("服务起来了", app.remote._srv is not None)
check("地址行有地址", ":" in app.remote_lbl.cget("text"),
      app.remote_lbl.cget("text"))
check("开启后二维码出现", bool(app.btn_remote_qr.winfo_manager()))
print(f"  地址: {app.remote_lbl.cget('text')}")
print(f"  URL: {app.remote.url}")

print("\n=== 7) 开关关闭 ===")
port = app.remote.port or 8765
app.v_remote.set(False)
app._on_remote_toggle()
pump(app, 16, 0.06)
check("config 为假", app._get("remote.enabled") is False)
check("服务停了", app.remote._srv is None)
check("地址行回到未开启", app.remote_lbl.cget("text") == "未开启",
      app.remote_lbl.cget("text"))
s = socket.socket()
released = False
try:
    s.bind(("0.0.0.0", port))
    released = True
except OSError:
    released = False
finally:
    s.close()
check(f"端口 {port} 已释放", released)

print("\n=== 8) 布局 ===")
RX, RY = app.root.winfo_rootx(), app.root.winfo_rooty()
RW = app.root.winfo_width()


def rel(w):
    return (w.winfo_rootx() - RX, w.winfo_rooty() - RY,
            w.winfo_width(), w.winfo_height())


for nm, wd in (("手机开关行", app.chk_remote), ("地址", app.remote_lbl),
               ("二维码", app.btn_remote_qr), ("OCR 下拉", app.cb_ocr_speed),
               ("OCR 提示", app.spd_hint)):
    if not wd.winfo_manager():
        print(f"  {nm:10s} 当前隐藏，跳过")
        continue
    x, y, w, h = rel(wd)
    print(f"  {nm:10s} x={x:4d} y={y:3d} w={w:3d} 右={x+w:4d}")
    check(f"{nm} 在窗口内", x + w <= RW)

print(f"  日志区高 {app.txt.winfo_height()}px")
check("日志区可用", app.txt.winfo_height() > 80)

app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)