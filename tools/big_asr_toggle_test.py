"""验证「大模型识别」开关：两个服务器都能用、无 key 时拒绝、状态同步。

用 config_guard 包住，跑完自动还原 config.json（不会再清掉用户的 key）。
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cfg_guard import config_guard

from valotalk.app import App
from valotalk.config import CONFIG

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


with config_guard():
    app = App()
    app._running = True
    pump(app, 20, 0.08)

    print("=== 1) 开关存在且默认开（配了 key）===")
    has_key = app.asr_cloud.available()
    print(f"  v_big_asr = {app.v_big_asr.get()}")
    print(f"  配置 backend = {app._get('asr.backend')}")
    print(f"  标签 = {app.big_asr_lbl.cget('text')!r}")
    print(f"  有 API key: {has_key}")
    check("有 chk_big_asr 控件", hasattr(app, "chk_big_asr"))
    check("有状态标签", hasattr(app, "big_asr_lbl"))
    if has_key:
        check("默认开着", app.v_big_asr.get() is True)
        check("标签显示服务商", "key" not in app.big_asr_lbl.cget("text").lower(),
              app.big_asr_lbl.cget("text"))
    else:
        check("无 key 时默认关", app.v_big_asr.get() is False)
        check("标签提示未配 key", "key" in app.big_asr_lbl.cget("text").lower())

    print("\n=== 2) 关掉 → 两个服务器都走本地 ===")
    app.v_big_asr.set(False)
    app._on_big_asr_toggle()
    pump(app, 6)
    print(f"  backend = {app._get('asr.backend')}")
    check("配置变 local", app._get("asr.backend") == "local")
    for lang in ("en", "ja"):
        used = app._use_cloud_asr(lang)
        print(f"  {lang} 用云端? {used}")
        check(f"关掉后 {lang} 不走云端", used is False)
    check("标签显示用本地", "本地" in app.big_asr_lbl.cget("text"),
          app.big_asr_lbl.cget("text"))

    print("\n=== 3) 打开 → 两个服务器都走大模型 ===")
    if has_key:
        app.v_big_asr.set(True)
        app._on_big_asr_toggle()
        pump(app, 10)
        print(f"  backend = {app._get('asr.backend')}")
        check("配置变 cloud", app._get("asr.backend") == "cloud")
        for lang in ("en", "ja"):
            used = app._use_cloud_asr(lang)
            print(f"  {lang} 用云端? {used}")
            check(f"打开后 {lang} 走云端", used is True)
        check("标签显示服务商", len(app.big_asr_lbl.cget("text")) > 2,
              app.big_asr_lbl.cget("text"))
    else:
        print("  没有 key，跳过")

    print("\n=== 4) 没 key 时打开应该被拒绝 ===")
    CONFIG.set("asr.cloud_api_key", "", save=False)
    CONFIG.set("translate.llm.api_key", "", save=False)
    app.asr_cloud.close()
    app.v_big_asr.set(True)
    app._on_big_asr_toggle()
    pump(app, 6)
    print(f"  开关状态 = {app.v_big_asr.get()}  backend = {app._get('asr.backend')}")
    check("开关被复位成关", app.v_big_asr.get() is False)
    check("backend 是 local", app._get("asr.backend") == "local")
    check("标签提示未配 key", "key" in app.big_asr_lbl.cget("text").lower(),
          app.big_asr_lbl.cget("text"))

    print("\n=== 5) 服务器那一行的标签也跟着变 ===")
    app.asr_cloud.close()
    app._refresh_asr_mode_label("en")
    pump(app, 4)
    t_en = app.asr_mode_lbl.cget("text")
    app._refresh_asr_mode_label("ja")
    pump(app, 4)
    t_ja = app.asr_mode_lbl.cget("text")
    print(f"  无 key · 英服: {t_en!r}")
    print(f"  无 key · 日服: {t_ja!r}")
    check("无 key 时两个服务器都提示",
          "key" in t_en.lower() and "key" in t_ja.lower(), f"{t_en} / {t_ja}")

    # 恢复 key（guard 退出时会整体还原，这里只是让后续步骤能看到"有 key"的状态）
    _orig_key = CONFIG._data.get("translate", {}).get("llm", {}).get("api_key")
    if _orig_key:
        CONFIG.set("translate.llm.api_key", _orig_key, save=False)

    print("\n=== 6) 布局 ===")
    RX = app.root.winfo_rootx()
    RW = app.root.winfo_width()
    for nm, wd in (("大模型开关行", app.chk_big_asr), ("状态标签", app.big_asr_lbl)):
        x = wd.winfo_rootx() - RX
        w = wd.winfo_width()
        print(f"  {nm:12s} x={x:4d} w={w:3d} 右={x+w:4d}")
        check(f"{nm} 在窗口内", x + w <= RW)

    print(f"  日志区高 {app.txt.winfo_height()}px")
    check("日志区可用", app.txt.winfo_height() > 80)

    app.shutdown()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)