"""模拟完整更新流程：点「立即更新」→ 下载 → 应用（用临时副本）。

真身不动，验证界面状态机：
  初始 → 下载中(进度条) → 完成(立即重启按钮)
"""
from __future__ import annotations
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.app import App
from valotalk import updater
from valotalk.update_ui import UpdateDialog

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cache"


def pump(app, n=10, gap=0.05):
    for _ in range(n):
        app.root.update()
        time.sleep(gap)


def shot(win, path, pad=12):
    import mss
    import numpy as np
    from PIL import Image
    factory = getattr(mss, "MSS", None) or mss.mss
    win.update_idletasks()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    with factory() as sct:
        g = sct.grab({"left": x - pad, "top": y - pad,
                      "width": w + pad * 2, "height": h + pad * 2})
        arr = np.asarray(g)[:, :, :3][:, :, ::-1]
    Image.fromarray(arr).save(path)
    print(f"  已保存 {path.name}")


def main():
    app = App()
    app._running = True
    pump(app, 16, 0.08)

    # 把 apply 的目标指到临时目录，别动真身
    tmp = ROOT / "cache" / "ui_update_repo"
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "valotalk").mkdir(parents=True)
    (tmp / "valotalk" / "app.py").write_text("# OLD\n", encoding="utf-8")
    (tmp / "run.bat").write_text("@echo off\n", encoding="utf-8")

    import valotalk.updater as u
    real_root = u.ROOT
    u.ROOT = tmp
    upd = u.Updater(app._get, log=app.log)

    info = updater.UpdateInfo(version="2.1.2",
                             notes="- 播放锁改成类级\n- sd.play() 播完才返回")
    dlg = UpdateDialog(app.root, info, upd,
                       on_applied=lambda: print("  [回调] 重启"),
                       log=app.log,
                       on_later=lambda: print("  [回调] 下次再说"))
    pump(app, 12, 0.06)
    shot(dlg.top, OUT / "update_1_initial.png")
    print(f"  初始: 按钮={dlg.btn_now._text}  进度条={bool(dlg.prog_wrap.winfo_manager())}")

    # 点「立即更新」
    dlg._update_now()
    pump(app, 8, 0.05)
    shot(dlg.top, OUT / "update_2_downloading.png")
    print(f"  下载中: 按钮={dlg.btn_now._text}  进度条={bool(dlg.prog_wrap.winfo_manager())}")

    # 等后台完成（最多 120s）
    t0 = time.time()
    while dlg._busy and time.time() - t0 < 120:
        pump(app, 4, 0.1)
    pump(app, 10, 0.06)

    print(f"  结束: busy={dlg._busy}  按钮={dlg.btn_now._text}  hint={dlg.hint.cget('text')}")
    shot(dlg.top, OUT / "update_3_done.png")

    # 检查临时目录是否真被覆盖
    new_app = (tmp / "valotalk" / "app.py").read_text(encoding="utf-8", errors="ignore")
    print(f"  临时目录 app.py: {'已覆盖 (class App)' if 'class App' in new_app else '仍是旧的'}")
    print(f"  文件数: {len([p for p in (tmp/'valotalk').rglob('*.py')])}")

    u.ROOT = real_root
    dlg.top.destroy()
    shutil.rmtree(tmp, ignore_errors=True)
    app.shutdown()


if __name__ == "__main__":
    main()