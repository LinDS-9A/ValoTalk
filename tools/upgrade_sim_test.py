"""模拟 v2.3.0 用户点「检查更新」→ 下载 → 覆盖 → 启动。

只验证**更新后能不能起来**，不真的发版：
- 用 v2.3.0 的 UPDATE_FILES 清单（模拟老版 updater 行为）
- 只覆盖清单里那 20 个文件
- 然后尝试启动，看会不会因为缺 profiles/envcheck/assets 而崩
"""
from __future__ import annotations
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="vt_upgrade_"))

print("=" * 58)
print("模拟 v2.3.0 → v3.0.0-beta 更新")
print("=" * 58)

# v2.3.0 的更新清单（老版 updater 只下这些）
OLD_LIST = [
    "valotalk/__init__.py", "valotalk/__main__.py", "valotalk/app.py",
    "valotalk/asr.py", "valotalk/asr_cloud.py", "valotalk/capture.py",
    "valotalk/config.py", "valotalk/ocr.py", "valotalk/overlay.py",
    "valotalk/remote.py", "valotalk/terms.py", "valotalk/translate.py",
    "valotalk/tts.py", "valotalk/ui_theme.py", "valotalk/winapi.py",
    "valotalk/updater.py", "valotalk/update_ui.py",
    "run.bat", "README.md", "CHANGELOG.md",
]

# 1) 造一个「v2.3.0 的安装目录」：当前代码 + 删掉新文件
print(f"\n[1] 准备干净目录 {TMP}")
for rel in OLD_LIST:
    src = ROOT / rel
    if not src.exists():
        print(f"    !! 缺源文件 {rel}")
        continue
    dst = TMP / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
print(f"    复制了 {len(OLD_LIST)} 个文件（老清单）")

# 模拟老版本没有这些新文件
for gone in ("valotalk/profiles.py", "valotalk/envcheck.py",
             "valotalk/assets"):
    p = TMP / gone
    if p.exists():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
print("    已移除 profiles.py / envcheck.py / assets/（模拟老用户）")

# 配置文件也带过去（不然没配置可读）
cfg = ROOT / "config.json"
if cfg.exists():
    shutil.copy2(cfg, TMP / "config.json")

# 2) 启动试试
print("\n[2] 尝试启动（不带任何人工干预，看自愈能不能兜住）")
probe = f"""
import sys, time
sys.path.insert(0, r'{TMP}')
from valotalk.app import App
a = App()
a._running = True
for _ in range(16):
    a.root.update()
    time.sleep(0.06)
print('WINDOW_OK', a.root.winfo_width(), a.root.winfo_height())
a.shutdown()
"""
probe_file = TMP / "_probe.py"
probe_file.write_text(probe, encoding="utf-8")

r = subprocess.run(
    [sys.executable, "-X", "utf8", str(probe_file)],
    cwd=str(TMP), capture_output=True, text=True, encoding="utf-8",
    errors="replace", timeout=180)

out = (r.stdout or "") + (r.stderr or "")
ok = "WINDOW_OK" in out

print("\n[3] 结果")
for line in out.strip().splitlines()[-14:]:
    print("   ", line)

if ok:
    # 检查自愈后生成了什么
    print("\n[4] 自愈产物")
    for name in ("profiles.py", "envcheck.py"):
        p = TMP / "valotalk" / name
        if p.exists():
            head = p.read_text(encoding="utf-8", errors="replace")[:50]
            kind = "降级实现" if "降级版" in head else "正式版"
            print(f"    {name}: {p.stat().st_size} 字节（{kind}）")
        else:
            print(f"    {name}: 不存在")

print("\n" + "=" * 58)
print("更新后能启动 ✅" if ok else "更新后启动失败 ❌")
print(f"临时目录：{TMP}")
print("=" * 58)
sys.exit(0 if ok else 1)
