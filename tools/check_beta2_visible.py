"""验证：跑着 v3.0.0-beta 的用户，能不能检测到 v3.0.0-beta2。

关键点是 parse_version 怎么处理 beta / beta2 后缀。
"""
from __future__ import annotations
import subprocess
import sys
import tempfile
from pathlib import Path

GIT = r"E:\rea-work\.tools\git\cmd\git.exe"
ROOT = Path(r"E:\rea-work\valotalk")
TMP = Path(tempfile.mkdtemp(prefix="vt_pv_"))

for rel in ("valotalk/updater.py", "valotalk/__init__.py"):
    r = subprocess.run([GIT, "show", f"v3.0.0-beta:{rel}"],
                       cwd=str(ROOT), capture_output=True)
    p = TMP / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(r.stdout)

probe = f'''
import sys
sys.path.insert(0, r"{TMP}")
from valotalk.updater import Updater, parse_version

print("=== parse_version 的解析结果 ===")
for v in ("3.0.0-beta", "3.0.0-beta2", "3.0.0", "2.3.0"):
    print(f"  {{v:14s}} -> {{parse_version(v)}}")

print()
print("=== beta 用户点检查更新 ===")
u = Updater(lambda k, d=None: d)
info = u.check(timeout=25)
if info is None:
    print("  结果: None（认为已是最新，检测不到 beta2）")
    print("  last_error:", u.last_error or "(空)")
else:
    print("  结果: 发现新版本", info.version)
'''

pf = TMP / "_p.py"
pf.write_text(probe, encoding="utf-8")
r = subprocess.run([sys.executable, "-X", "utf8", str(pf)], cwd=str(TMP),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
print("=== 用 v3.0.0-beta 的 updater（beta 用户的真实版本）===")
for line in (r.stdout + r.stderr).strip().splitlines():
    print(line)
