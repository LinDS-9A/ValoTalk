"""验证 v3.0.1-beta 发布效果（全部走 CDN，不依赖 git 网络）。

1. 各旧版本的 updater（从 CDN 取当时那份代码）能否检测到 3.0.1-beta
2. 新版 _latest_version 的双来源（jsdelivr + GitHub）是否正常
3. 远端 __init__.py 的 PRERELEASE 标记是否读得到
4. dist zip 能否下载、内容是否齐全
"""
from __future__ import annotations
import io
import json
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://cdn.jsdelivr.net/gh/LinDS-9A/ValoTalk"
TARGET = "3.0.1-beta"
ROOT = Path(__file__).resolve().parent.parent


def fetch(url: str, timeout: float = 30.0) -> bytes | None:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ValoTalk/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


print("=" * 68)
print(f"[1] 各旧版本能否检测到 {TARGET}")
print("=" * 68)

for tag in ("v3.0.0-beta", "v3.0.0-beta2", "v2.3.0"):
    tmp = Path(tempfile.mkdtemp(prefix="vt_cdn_"))
    ok_export = True
    for rel in ("valotalk/updater.py", "valotalk/__init__.py"):
        data = fetch(f"{BASE}@{tag}/{rel}")
        if not data:
            ok_export = False
            break
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    if not ok_export:
        print(f"  {tag:14s} → 取不到该版本代码")
        continue

    probe = f'''
import sys
sys.path.insert(0, r"{tmp}")
from valotalk.updater import Updater
u = Updater(lambda k, d=None: d)
info = u.check(timeout=25)
print("LOCAL|" + u.local_version())
if info is None:
    print("NONE|" + (u.last_error or ""))
else:
    print("OK|" + info.version + "|" + str(getattr(info, "prerelease", "?")))
'''
    pf = tmp / "_p.py"
    pf.write_text(probe, encoding="utf-8")
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", str(pf)],
                       cwd=str(tmp), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    lines = [l for l in (r.stdout or "").strip().splitlines() if "|" in l]
    local = next((l.split("|")[1] for l in lines if l.startswith("LOCAL|")), "?")
    ok_line = next((l for l in lines if l.startswith("OK|")), None)
    none_line = next((l for l in lines if l.startswith("NONE|")), None)
    if ok_line:
        _, ver, pre = ok_line.split("|", 2)
        mark = "✅" if ver == TARGET else "❌"
        print(f"  {tag:14s} (本地 {local:12s}) → {ver:14s} {mark}")
    else:
        err = none_line.split("|", 1)[1] if none_line else "?"
        print(f"  {tag:14s} (本地 {local:12s}) → ❌ 检测不到 {err}")

print()
print("=" * 68)
print("[2] 新版双来源 & PRERELEASE 标记")
print("=" * 68)
sys.path.insert(0, str(ROOT))
from valotalk.updater import Updater  # noqa: E402

u = Updater(lambda k, d=None: d)
found = u._latest_version(15)
print(f"  _latest_version() → {found}")
gh = u._latest_from_github(15)
print(f"  GitHub 来源      → {gh}")
print(f"  远端 3.0.1-beta 的 PRERELEASE → {u._fetch_prerelease(TARGET)}")
print(f"  远端 2.3.0 的 PRERELEASE      → {u._fetch_prerelease('2.3.0')}")

print()
print("=" * 68)
print("[3] jsdelivr 版本列表")
print("=" * 68)
raw = fetch("https://data.jsdelivr.com/v1/packages/gh/LinDS-9A/ValoTalk")
if raw:
    vs = [v.get("version", "") for v in json.loads(raw).get("versions", [])]
    print(f"  前 4 个: {vs[:4]}")
    print(f"  含 {TARGET}: {TARGET in vs}")

print()
print("=" * 68)
print("[4] dist zip")
print("=" * 68)
data = fetch(f"{BASE}@v{TARGET}/dist/ValoTalk-v{TARGET}.zip", timeout=90)
if data:
    print(f"  下载 {len(data)/1024:.0f} KB ✅")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        ver = ""
        for line in z.read("ValoTalk/valotalk/__init__.py").decode().splitlines():
            if line.startswith("__version__"):
                ver = line.split("=")[1].strip().strip('"')
                break
        upd = z.read("ValoTalk/valotalk/updater.py").decode()
        print(f"  zip 内版本: {ver}")
        print(f"  含 GitHub 来源代码: {'_latest_from_github' in upd}")
        print(f"  含 PRERELEASE 标记: "
              f"{'PRERELEASE = True' in z.read('ValoTalk/valotalk/__init__.py').decode()}")
        key = [n.split("/")[-1] for n in names
               if any(k in n for k in ("profiles.py", "envcheck.py",
                                       "assets/bg.png", "assets/sponsor.png"))]
        print(f"  关键文件: {key}")
else:
    print("  ❌ 下载失败")
