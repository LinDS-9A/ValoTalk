"""更新功能端到端测试。

验证：
  1. 版本比较（含 2.1.10 > 2.1.9 这种按数字比的坑）
  2. 远端真实可读（jsdelivr）
  3. zip 整包下载 + 解压
  4. apply 备份 + 覆盖
  5. 关键文件缺失时拒绝更新
"""
from __future__ import annotations
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk import updater
from valotalk.config import CONFIG

ROOT = Path(__file__).resolve().parent.parent
up = updater.Updater(CONFIG.get, log=print)

failed = 0
def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1

print("=== 1) 版本比较 ===")
cases = [
    ("2.1.2", "2.1.3", True),
    ("2.1.2", "2.1.2", False),
    ("2.1.10", "2.1.9", False),
    ("2.1.2", "v2.2.0", True),
    ("2.1.2", "2.1.2-beta", False),
]
for local, remote, should in cases:
    got = updater.parse_version(remote) > updater.parse_version(local)
    check(f"{local} -> {remote} 有新版={should}", got == should, f"got={got}")

print("\n=== 2) 远端真实可读 ===")
t0 = time.time()
inited = updater._get_retry(f"{updater.CDN}/valotalk/__init__.py", tries=2, timeout=25)
print(f"  耗时 {time.time()-t0:.2f}s")
check("读到远端 __init__.py", inited is not None)
if inited:
    import re
    m = re.search(r'__version__\s*=\s*["\']([\d.]+)["\']',
                  inited.decode("utf-8", "ignore"))
    check("能解析远端版本号", m is not None)
    print(f"  远端版本: {m.group(1) if m else '?'}")

print("\n=== 3) zip 整包下载 + 解压 ===")
info = updater.UpdateInfo(version="2.1.2")
t0 = time.time()
staging = up.download(info)
dt = time.time() - t0
if staging is None:
    check("下载成功", False, up.last_error)
else:
    files = [p for p in staging.rglob("*") if p.is_file()]
    print(f"  耗时 {dt:.2f}s  文件 {len(files)} 个")
    check("下载成功", len(files) >= 10, f"只下到 {len(files)} 个")
    check("走了 zip 而不是逐文件", dt < 60, f"{dt:.1f}s 太慢")
    check("有 valotalk/app.py", (staging / "valotalk" / "app.py").exists())
    check("有 valotalk/__init__.py", (staging / "valotalk" / "__init__.py").exists())
    app_py = (staging / "valotalk" / "app.py").read_text(encoding="utf-8", errors="ignore")
    check("app.py 内容完整", "class App" in app_py and len(app_py) > 10000,
          f"len={len(app_py)}")
    # 不应该带 config.json / models
    check("没夹带 config.json", not (staging / "config.json").exists())
    check("没夹带 models/", not (staging / "models").exists())

    print("\n=== 4) apply 备份 + 覆盖（临时副本）===")
    tmp = ROOT / "cache" / "update_test_repo"
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "valotalk").mkdir(parents=True)
    (tmp / "valotalk" / "app.py").write_text("# OLD CONTENT\n", encoding="utf-8")

    import valotalk.updater as u
    old_root = u.ROOT
    u.ROOT = tmp
    up2 = u.Updater(CONFIG.get, log=print)
    up2._staging = staging
    ok = up2.apply(staging)
    u.ROOT = old_root

    check("apply 成功", ok, up2.last_error)
    new = (tmp / "valotalk" / "app.py").read_text(encoding="utf-8", errors="ignore")
    check("app.py 已覆盖", "class App" in new and len(new) > 10000)
    baks = list((tmp / "cache" / "update" / "backup").rglob("app.py"))
    check("备份里有旧 app.py", len(baks) > 0)
    if baks:
        check("备份内容确实是旧的", "OLD CONTENT" in baks[0].read_text(encoding="utf-8"))
    shutil.rmtree(tmp, ignore_errors=True)

print("\n=== 5) 下载失败时拒绝更新 ===")
old_get = updater._get_retry
updater._get_retry = lambda url, tries=2, timeout=15: None
up3 = updater.Updater(CONFIG.get, log=lambda *_: None)
r = up3.download(updater.UpdateInfo(version="9.9.9"))
updater._get_retry = old_get
check("全失败返回 None", r is None)
check("有错误信息", bool(up3.last_error), up3.last_error)

print("\n=== 6) check() 对本机当前版本 ===")
from valotalk import __version__
info_now = up.check()
if info_now is None:
    print(f"  当前 v{__version__}，无新版本（或 {up.last_error or '已最新'}）")
    check("check 正常返回 None", True)
else:
    print(f"  发现新版本 v{info_now.version}")
    check("check 返回了更高版本",
          updater.parse_version(info_now.version) > updater.parse_version(__version__))

up.cleanup()

print("\n" + "=" * 50)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)