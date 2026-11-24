"""端到端：完全按 v2.3.0 用户点「检查更新」的真实路径走一遍。

真实路径是（看 updater.download 的实现）：
  1) 先下 dist/ValoTalk-v{version}.zip（一次请求，4 秒左右）
  2) 解压，只取 valotalk/ + run.bat + README.md
  3) 覆盖到安装目录
  4) 重启

所以老用户拿到的是**完整包**（含 profiles/envcheck/assets），
自愈只是 zip 也下不到时的兜底。这里验证的就是这条主路径。
"""
from __future__ import annotations
import io
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://cdn.jsdelivr.net/gh/LinDS-9A/ValoTalk"
VERSION = "3.0.0-beta"
LOCAL = Path(r"E:\rea-work\valotalk")


def fetch(url: str, tries: int = 3, timeout: float = 90.0) -> bytes | None:
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ValoTalk-Updater/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if i < tries - 1:
                time.sleep(2)
    return None


TMP = Path(tempfile.mkdtemp(prefix="vt_e2e_zip_"))
print("=" * 64)
print(f"端到端：v2.3.0 → v{VERSION}（走 updater 的真实 zip 路径）")
print("=" * 64)
print(f"\n安装目录 {TMP}")

# ---- 1) 先放一个「v2.3.0 的安装目录」：只有老清单里的文件 ----
print("\n[1] 搭建 v2.3.0 安装现场")
OLD = [
    "valotalk/__init__.py", "valotalk/__main__.py", "valotalk/app.py",
    "valotalk/asr.py", "valotalk/asr_cloud.py", "valotalk/capture.py",
    "valotalk/config.py", "valotalk/ocr.py", "valotalk/overlay.py",
    "valotalk/remote.py", "valotalk/terms.py", "valotalk/translate.py",
    "valotalk/tts.py", "valotalk/ui_theme.py", "valotalk/winapi.py",
    "valotalk/updater.py", "valotalk/update_ui.py",
    "run.bat", "README.md", "CHANGELOG.md",
]
for rel in OLD:
    src = LOCAL / rel
    if src.exists():
        dst = TMP / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
print(f"    放了 {len(OLD)} 个文件（老清单）")
for gone in ("valotalk/profiles.py", "valotalk/envcheck.py", "valotalk/assets"):
    p = TMP / gone
    if p.exists():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
print("    确认 profiles/envcheck/assets 都不存在 ✓")

cfg = LOCAL / "config.json"
if cfg.exists():
    shutil.copy2(cfg, TMP / "config.json")
    print("    带了一份 config.json")

# ---- 2) 下载 zip ----
print(f"\n[2] 下载 dist/ValoTalk-v{VERSION}.zip")
url = f"{BASE}@v{VERSION}/dist/ValoTalk-v{VERSION}.zip"
t0 = time.time()
data = fetch(url)
if not data:
    print("    ✗ 下载失败")
    sys.exit(1)
print(f"    ✓ {len(data)/1024:.0f} KB，耗时 {time.time()-t0:.1f}s")

# ---- 3) 按 updater 的规则解压覆盖 ----
print("\n[3] 解压覆盖（规则和 updater._download_zip 一致）")
zp = TMP / "_update.zip"
zp.write_bytes(data)
applied = 0
skipped = []
with zipfile.ZipFile(zp) as z:
    names = z.namelist()
    tops = {n.split("/")[0] for n in names if "/" in n}
    top = tops.pop() if len(tops) == 1 else ""
    print(f"    压缩包顶层目录: {top!r}")
    for n in names:
        if n.endswith("/"):
            continue
        rel = n[len(top) + 1:] if top and n.startswith(top + "/") else n
        if not rel or rel.startswith(".."):
            continue
        if not (rel.startswith("valotalk/") or rel == "run.bat"
                or rel == "README.md"):
            skipped.append(rel)
            continue
        dst = TMP / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        with z.open(n) as s, open(dst, "wb") as o:
            shutil.copyfileobj(s, o)
        applied += 1
zp.unlink()
print(f"    覆盖 {applied} 个文件，跳过 {len(skipped)} 个（非更新范围）")

# ---- 4) 覆盖后检查关键文件 ----
print("\n[4] 覆盖后的文件清单")
ok = True
must = {
    "valotalk/__init__.py": 500,
    "valotalk/app.py": 100000,
    "valotalk/profiles.py": 5000,
    "valotalk/envcheck.py": 3000,
    "valotalk/ui_theme.py": 30000,
    "valotalk/updater.py": 10000,
    "valotalk/assets/bg.png": 500000,
    "valotalk/assets/sponsor.png": 50000,
    "run.bat": 1000,
}
for rel, min_size in must.items():
    p = TMP / rel
    if not p.exists():
        print(f"    ✗ {rel:32s} 缺失")
        ok = False
    elif p.stat().st_size < min_size:
        print(f"    ⚠ {rel:32s} 只有 {p.stat().st_size} 字节（期望 ≥{min_size}）")
        ok = False
    else:
        print(f"    ✓ {rel:32s} {p.stat().st_size} 字节")

# 版本号
init = (TMP / "valotalk/__init__.py").read_text(encoding="utf-8")
for line in init.splitlines():
    if line.startswith("__version__"):
        print(f"\n    版本: {line.strip()}")
        if VERSION not in line:
            ok = False
        break

# ---- 5) 启动 ----
print("\n[5] 启动")
probe = f"""
import sys, time
sys.path.insert(0, r'{TMP}')
import valotalk
print('BOOT_VERSION', valotalk.__version__)
from valotalk.app import App
a = App()
a._running = True
for _ in range(18):
    a.root.update()
    time.sleep(0.06)
print('WINDOW_OK', a.root.winfo_width(), a.root.winfo_height())
a.shutdown()
"""
pf = TMP / "_probe.py"
pf.write_text(probe, encoding="utf-8")
r = subprocess.run([sys.executable, "-X", "utf8", str(pf)], cwd=str(TMP),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=240)
out = (r.stdout or "") + (r.stderr or "")
started = "WINDOW_OK" in out
for line in out.strip().splitlines()[-10:]:
    print("     ", line)

print("\n" + "=" * 64)
print("老用户更新后完整可用 ✅" if (ok and started) else "有问题 ❌")
print(f"目录：{TMP}")
print("=" * 64)
sys.exit(0 if (ok and started) else 1)
