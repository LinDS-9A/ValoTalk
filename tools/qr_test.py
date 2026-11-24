"""验证手机遥控二维码：正常路径 + 缺库路径。"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


with config_guard():
    from valotalk.app import App

    app = App()
    app._running = True
    for _ in range(28):
        app.root.update()
        time.sleep(0.07)

    url = app.remote.url
    print(f"遥控地址: {url!r}")
    if not url:
        print("遥控没起来，先打开开关")
        app.chk_remote.var.set(True)
        try:
            app._on_remote_toggle()
        except Exception:
            pass
        for _ in range(30):
            app.root.update()
            time.sleep(0.08)
        url = app.remote.url
        print(f"再取: {url!r}")

    def toplevels():
        return [w for w in app.root.winfo_children()
                if w.winfo_class() == "Toplevel" and w.title() == "手机遥控"]

    print("\n=== 1) 正常路径（qrcode 已装）===")
    check("有遥控地址", bool(url), repr(url))
    app._show_remote_qr()
    for _ in range(14):
        app.root.update()
        time.sleep(0.06)
    tops = toplevels()
    print(f"  弹出 {len(tops)} 个「手机遥控」窗口")
    check("弹出了二维码窗口", len(tops) == 1)
    if tops:
        t = tops[0]
        t.update_idletasks()
        print(f"  尺寸 {t.winfo_width()}x{t.winfo_height()}  "
              f"viewable={t.winfo_viewable()}  topmost={t.attributes('-topmost')}")
        check("窗口可见", bool(t.winfo_viewable()))
        check("窗口是置顶的", bool(t.attributes("-topmost")))
        # 里面应该有张 250x250 的图
        imgs = []

        def walk(w):
            for c in w.winfo_children():
                if c.winfo_class() == "Label":
                    try:
                        if c.cget("image"):
                            imgs.append(c)
                    except Exception:
                        pass
                walk(c)

        walk(t)
        print(f"  带图的 Label: {len(imgs)}")
        check("二维码图片显示了", len(imgs) >= 1,
              f"{[ (c.winfo_width(), c.winfo_height()) for c in imgs ]}")
        if imgs:
            iw, ih = imgs[0].winfo_width(), imgs[0].winfo_height()
            check("图片尺寸合理（≈250）", abs(iw - 250) < 30 and abs(ih - 250) < 30,
                  f"{iw}x{ih}")
        t.destroy()
        for _ in range(4):
            app.root.update()

    print("\n=== 2) 缺库路径（把 qrcode 屏蔽掉）===")
    saved = {}
    for k in list(sys.modules):
        if k == "qrcode" or k.startswith("qrcode."):
            saved[k] = sys.modules.pop(k)
    sys.modules["qrcode"] = None      # 让 import 抛 ImportError
    try:
        app._install_qrcode_then_show("http://192.168.1.7:8765")
        for _ in range(8):
            app.root.update()
            time.sleep(0.05)
        tips = [w for w in app.root.winfo_children()
                if w.winfo_class() == "Toplevel"
                and ("正在准备" in str(w.title()) or w.title() == "手机遥控")]
        print(f"  安装提示窗口: {len(tips)} 个")
        check("缺库时给了提示框（不是静默失败）", len(tips) >= 1)
        for t in tips:
            t.destroy()
    finally:
        sys.modules.pop("qrcode", None)
        sys.modules.update(saved)
    for _ in range(4):
        app.root.update()

    app.shutdown()

print("\n" + "=" * 56)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 56)
sys.exit(0 if failed == 0 else 1)
