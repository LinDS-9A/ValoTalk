"""验证默认值 + 手机遥控移到功能开关区之后的状态。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App
from valotalk.config import DEFAULTS
from valotalk.ocr import ChatOCR

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


def pump(app, n=14, gap=0.06):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


print("=== 1) 配置默认值 ===")
print(f"  DEFAULTS.remote.enabled  = {DEFAULTS['remote']['enabled']}")
print(f"  DEFAULTS.ocr.onnx_threads = {DEFAULTS['ocr']['onnx_threads']}")
check("手机遥控默认关", DEFAULTS["remote"]["enabled"] is False)
check("OCR 默认 2 线程", DEFAULTS["ocr"]["onnx_threads"] == 2)
check("2 线程对应 650ms 档", "650" in ChatOCR.SPEED_CHOICES[2])
check("ChatOCR.DEFAULT_THREADS == 2", ChatOCR.DEFAULT_THREADS == 2)

print("\n=== 2) 三档文字 ===")
for n in (1, 2, 4):
    print(f"  {n} 线程 → {ChatOCR.SPEED_CHOICES[n]}")
check("1 线程 829ms", "829" in ChatOCR.SPEED_CHOICES[1])
check("2 线程 650ms", "650" in ChatOCR.SPEED_CHOICES[2])
check("4 线程 625ms", "625" in ChatOCR.SPEED_CHOICES[4])

print("\n=== 3) 启动后 UI 状态 ===")
app = App()
app._running = True
pump(app, 22, 0.08)

print(f"  手机开关变量 = {app.v_remote.get()}")
print(f"  地址行文字   = {app.remote_lbl.cget('text')}")
print(f"  OCR 下拉     = {app.cb_ocr_speed.get()}")
print(f"  OCR 线程     = {app._get('ocr.onnx_threads')}")

check("手机开关默认关", app.v_remote.get() is False)
check("地址行显示未开启", app.remote_lbl.cget("text") == "未开启",
      app.remote_lbl.cget("text"))
check("手机服务没起来", app.remote._srv is None)
check("OCR 下拉显示 650ms 档", "650" in app.cb_ocr_speed.get(),
      app.cb_ocr_speed.get())
check("ChatOCR 内部线程数 = 2", app.ocr.threads() == 2, str(app.ocr.threads()))

print("\n=== 4) 手机遥控在功能开关区（同一行）===")
print(f"  开关所在卡片 = {app.chk_remote.master}")
print(f"  地址标签父容器 = {app.remote_lbl.master}")
check("地址在开关行的 extra 区",
      app.remote_lbl.master is app.chk_remote.extra)
check("二维码也在 extra 区",
      app.btn_remote_qr.master is app.chk_remote.extra)
# 该卡片里应该有其它功能开关
siblings = [w for w in app.chk_remote.master.winfo_children()
            if w.winfo_class() == "Frame" and hasattr(w, "switch")]
print(f"  该卡片里有 {len(siblings)} 个开关行")
check("在同一区域（还有其它功能开关）", len(siblings) >= 5, str(len(siblings)))

print("\n=== 5) 打开/关闭 ===")
app.v_remote.set(True)
app._on_remote_toggle()
pump(app, 30)
check("开启后 config 为真", app._get("remote.enabled") is True)
check("服务起来了", app.remote._srv is not None)
check("地址行显示地址", ":" in app.remote_lbl.cget("text"),
      app.remote_lbl.cget("text"))
print(f"  地址行: {app.remote_lbl.cget('text')}")
print(f"  完整 URL: {app.remote.url}")

app.v_remote.set(False)
app._on_remote_toggle()
pump(app, 14)
check("关闭后 config 为假", app._get("remote.enabled") is False)
check("服务停了", app.remote._srv is None)
check("地址行回到未开启", app.remote_lbl.cget("text") == "未开启",
      app.remote_lbl.cget("text"))

print("\n=== 6) 快捷键卡片里不再有手机 ===")
# hk_combos 存的是 RoundCombo 控件，往上三层是卡片 canvas
hk_card = app.hk_combos["ptt"].master.master.master


def walk_texts(w, out):
    for c in w.winfo_children():
        try:
            if c.winfo_class() == "Label":
                out.append(c.cget("text"))
            elif c.winfo_class() == "Canvas":
                out.append(getattr(c, "_text", ""))
        except Exception:
            pass
        walk_texts(c, out)


texts = []
walk_texts(hk_card, texts)
print(f"  快捷键卡片内文字: {[t for t in texts if t][:12]}")
check("快捷键卡片里没有「手机」", not any("手机" in t for t in texts if t))
check("快捷键卡片里没有「二维码」", not any("二维码" in t for t in texts if t))

print("\n=== 7) 布局 ===")
RX, RY = app.root.winfo_rootx(), app.root.winfo_rooty()
RW, RH = app.root.winfo_width(), app.root.winfo_height()
def rel(w):
    return (w.winfo_rootx() - RX, w.winfo_rooty() - RY,
            w.winfo_width(), w.winfo_height())

for nm, wd in (("手机开关行", app.chk_remote), ("地址", app.remote_lbl),
               ("二维码按钮", app.btn_remote_qr), ("OCR 下拉", app.cb_ocr_speed)):
    if not wd.winfo_manager():
        print(f"  {nm:12s} 当前隐藏，跳过")
        continue
    x, y, w, h = rel(wd)
    print(f"  {nm:12s} x={x:4d} y={y:3d} w={w:3d} 右={x+w:4d}")
    check(f"{nm} 在窗口内", x + w <= RW)

print(f"  左列高度: {rel(app.chk_remote.master.master)[3]}px")
print(f"  日志区高 {app.txt.winfo_height()}px")
check("日志区可用", app.txt.winfo_height() > 80)

app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)