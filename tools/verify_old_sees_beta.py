"""验证 v2.3.0 的用户点「检查更新」时会看到什么。

用 v2.3.0 那个版本的 updater 代码去查（不是现在的），
因为它才是老用户本地真正跑的逻辑。
"""
from __future__ import annotations
import importlib.util
import sys
import tempfile
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(r"E:\rea-work\valotalk")
TMP = Path(tempfile.mkdtemp(prefix="vt_oldchk_"))
print("=" * 64)
print("用 v2.3.0 的 updater 代码检查更新")
print("=" * 64)

# 导出 v2.3.0 的 updater.py 和 __init__.py
import subprocess as sp
GIT = r"E:\rea-work\.tools\git\cmd\git.exe"
for rel in ("valotalk/updater.py", "valotalk/__init__.py"):
    r = sp.run([GIT, "show", f"v2.3.0:{rel}"], cwd=str(ROOT),
               capture_output=True)
    if r.returncode != 0:
        print(f"  导出 {rel} 失败")
        sys.exit(1)
    dst = TMP / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.stdout)
    print(f"  导出 {rel}  {len(r.stdout)} 字节")

# v2.3.0 的 updater 需要同目录下有 __init__.py（读 __version__）
init_txt = (TMP / "valotalk/__init__.py").read_text(encoding="utf-8")
ver = ""
for line in init_txt.splitlines():
    if line.startswith("__version__"):
        ver = line.split("=")[1].strip().strip('"').strip("'")
print(f"  该版本的 __version__ = {ver}")

# 用子进程跑（避免污染当前进程的 valotalk）
probe = f"""
import sys
sys.path.insert(0, r'{TMP}')
from valotalk.updater import Updater, parse_version
# v2.3.0 的签名是 __init__(self, cfg_get, log=None)
u = Updater(lambda key, default=None: default)
info = u.check(timeout=25)
if info is None:
    print('RESULT none')
    print('ERROR', u.last_error)
    sys.exit(0)
print('RESULT ok')
print('VERSION', info.version)
print('TAG', info.tag)
print('FILES', len(info.files))
notes = (info.notes or '')
print('NOTES_LEN', len(notes))
print('HAS_BETA_WORD', '测试版' in notes)
print('NOTES_HEAD', notes[:120].replace(chr(10), ' | '))
print('LOCAL', u.local_version())
print('CMP', parse_version(info.version), '>', parse_version(u.local_version()))
"""
pf = TMP / "_probe.py"
pf.write_text(probe, encoding="utf-8")
r = sp.run([sys.executable, "-X", "utf8", str(pf)], cwd=str(TMP),
           capture_output=True, text=True, encoding="utf-8",
           errors="replace", timeout=120)

out = (r.stdout or "") + (r.stderr or "")
print("\n[结果]")
kv = {}
for line in out.splitlines():
    print("   ", line)
    if " " in line:
        k, v = line.split(" ", 1)
        kv[k] = v

print("\n" + "=" * 64)
ok = kv.get("RESULT") == "ok" and kv.get("VERSION", "").startswith("3.0.0")
if ok:
    print(f"✅ v2.3.0 能检测到 {kv.get('VERSION')}")
    print(f"   老用户看到的版本变化：v{ver}  →  v{kv.get('VERSION')}")
    if kv.get("HAS_BETA_WORD") == "True":
        print("   更新说明里包含「测试版」字样 ✅")
    else:
        print("   ⚠ 更新说明里没找到「测试版」字样")
    print(f"   tag = {kv.get('TAG')}")
else:
    print("❌ 检测不到新版本")
    print(f"   RESULT={kv.get('RESULT')} ERROR={kv.get('ERROR')}")
print("=" * 64)
sys.exit(0 if ok else 1)
