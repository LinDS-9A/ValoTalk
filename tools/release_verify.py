"""发版后验证：老版本能否查到 v2.2.0 并完整下载。

这是最关键的一步 —— v2.1.3-beta 就是因为 jsdelivr @main 缓存，
发布了却查不到新版本才撤回的。
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REPO = "LinDS-9A/ValoTalk"
UA = {"User-Agent": "vt", "Accept": "*/*"}


def get(url, timeout=30):
    t0 = time.time()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), time.time() - t0


print("=== 1) 版本列表 API（检查更新用）===")
data, dt = get(f"https://data.jsdelivr.com/v1/packages/gh/{REPO}")
vs = [v["version"] for v in json.loads(data)["versions"]]
print(f"  {dt:.2f}s  versions={vs[:6]}")
ok1 = vs and vs[0] == "2.2.0"
print(f"  最新是 2.2.0: {'✓' if ok1 else '✗ 实际是 ' + (vs[0] if vs else '?')}")

print("\n=== 2) @tag 读 __init__.py（兜底路径）===")
try:
    raw, dt = get(f"https://cdn.jsdelivr.net/gh/{REPO}@v2.2.0/valotalk/__init__.py")
    txt = raw.decode("utf-8", "ignore")
    ver = [l for l in txt.splitlines() if "__version__" in l]
    print(f"  {dt:.2f}s  {ver[0].strip() if ver else '?'}")
    ok2 = ver and "2.2.0" in ver[0]
    print(f"  是 2.2.0: {'✓' if ok2 else '✗'}")
except Exception as e:
    print(f"  失败: {type(e).__name__} {e}")
    ok2 = False

print("\n=== 3) dist/ 里的更新包能下到吗 ===")
url = f"https://cdn.jsdelivr.net/gh/{REPO}@v2.2.0/dist/ValoTalk-v2.2.0.zip"
try:
    for attempt in (1, 2):
        data, dt = get(url, timeout=90)
        print(f"  第{attempt}次 {dt:5.1f}s  {len(data)} B  "
              f"{'ZIP ✓' if data[:2] == b'PK' else '不是 zip ✗'}")
    ok3 = data[:2] == b"PK" and len(data) > 100000
except Exception as e:
    print(f"  失败: {type(e).__name__} {e}")
    ok3 = False

print("\n=== 4) 模拟 v2.1.2 用户走完整检查流程 ===")
from valotalk import updater
from valotalk.config import CONFIG

up = updater.Updater(CONFIG.get, log=print)
t0 = time.time()
info = up.check()
dt = time.time() - t0
if info is None:
    print(f"  check() 返回 None（{up.last_error or '已是最新'}） —— 本机就是 2.2.0，正常")
    ok4 = True
else:
    print(f"  {dt:.2f}s  发现 v{info.version}，说明 {len(info.notes)} 字符")
    ok4 = updater.parse_version(info.version) > updater.parse_version("2.2.0")

# 假装本机是 2.1.2，看能不能发现 2.2.0
class Old(updater.Updater):
    def local_version(self):
        return "2.1.2"

old = Old(CONFIG.get, log=print)
info2 = old._latest_version(15)
print(f"\n  假装本机 2.1.2 → 查到远端 {info2}")
ok5 = info2 == "2.2.0"
print(f"  能发现新版本: {'✓' if ok5 else '✗'}")

print("\n=== 5) 下载 + 解压 ===")
if ok1:
    t0 = time.time()
    staging = old.download(updater.UpdateInfo(version="2.2.0"))
    dt = time.time() - t0
    if staging:
        files = [p for p in staging.rglob("*") if p.is_file()]
        print(f"  {dt:.2f}s  解压出 {len(files)} 个文件")
        init = (staging / "valotalk" / "__init__.py").read_text(encoding="utf-8")
        print(f"  包内版本: {[l for l in init.splitlines() if '__version__' in l]}")
        has_upd = (staging / "valotalk" / "updater.py").exists()
        print(f"  含 updater.py: {has_upd}")
        ok6 = len(files) >= 10 and "2.2.0" in init
    else:
        print(f"  下载失败: {old.last_error}")
        ok6 = False
    old.cleanup()
else:
    ok6 = False

print("\n" + "=" * 52)
allok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6
print("全部通过 ✅ 老版本用户能正常更新到 v2.2.0" if allok else "有失败项 ❌")
print("=" * 52)
sys.exit(0 if allok else 1)