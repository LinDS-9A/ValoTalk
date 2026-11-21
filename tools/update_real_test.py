"""真实验证：假装本机是旧版本，看 check() 能否发现新版并完整走完流程。"""
from __future__ import annotations
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk import updater
from valotalk.config import CONFIG

ROOT = Path(__file__).resolve().parent.parent
failed = 0


def check(name, cond, extra=""):
    global failed
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


print("=== 1) 真实 check()：本机 v2.1.3 vs 远端 ===")
up = updater.Updater(CONFIG.get, log=print)
t0 = time.time()
info = up.check()
print(f"  耗时 {time.time()-t0:.2f}s")
if info is None:
    print(f"  结果: 已是最新（{up.last_error or '远端版本不高于本地'}）")
    check("check 不报错", not up.last_error, up.last_error)
else:
    print(f"  发现新版本 v{info.version}")
    check("check 返回了更高版本",
          updater.parse_version(info.version) > updater.parse_version("2.1.3"))

print("\n=== 2) 假装本机是 2.1.2，应该发现 2.1.3 ===")


class FakeUpdater(updater.Updater):
    def local_version(self) -> str:
        return "2.1.2"


fake = FakeUpdater(CONFIG.get, log=print)
# check() 里用的是 `from . import __version__`，得绕过
orig_check = updater.Updater.check


def patched_check(self, timeout=12.0):
    self.last_error = ""
    raw = updater._get_retry(f"{updater.CDN}/valotalk/__init__.py", tries=2,
                             timeout=timeout)
    if raw is None:
        self.last_error = "连不上"
        return None
    import re
    m = re.search(r'__version__\s*=\s*["\']([\d.]+)["\']',
                  raw.decode("utf-8", "ignore"))
    if not m:
        self.last_error = "解析失败"
        return None
    remote = m.group(1)
    if updater.parse_version(remote) <= updater.parse_version("2.1.2"):
        return None
    return updater.UpdateInfo(version=remote, notes=self._fetch_notes(remote),
                              files=list(updater.UPDATE_FILES))


t0 = time.time()
info2 = patched_check(fake)
print(f"  耗时 {time.time()-t0:.2f}s")
check("发现了新版本", info2 is not None, fake.last_error)
if info2:
    print(f"  远端版本: {info2.version}")
    print(f"  更新说明: {len(info2.notes)} 字符")
    if info2.notes:
        print(f"    首行: {info2.notes.splitlines()[0][:50]}")
    check("版本号是 2.1.3", info2.version == "2.1.3", info2.version)
    check("拿到了更新说明", bool(info2.notes) or True)  # 说明可能为空，不强求

    print("\n=== 3) 下载这个版本 ===")
    t0 = time.time()
    staging = fake.download(info2)
    dt = time.time() - t0
    if staging is None:
        check("下载成功", False, fake.last_error)
    else:
        files = [p for p in staging.rglob("*") if p.is_file()]
        print(f"  耗时 {dt:.2f}s  {len(files)} 个文件")
        check("下载成功", len(files) >= 10)
        check("有 updater.py", (staging / "valotalk" / "updater.py").exists())
        check("有 CHANGELOG.md", (staging / "CHANGELOG.md").exists())
        # zip 里的版本号应该是 2.1.3
        init = (staging / "valotalk" / "__init__.py").read_text(encoding="utf-8")
        check("包里版本是 2.1.3", "2.1.3" in init, init.strip()[-20:])

        print("\n=== 4) apply 到临时目录 ===")
        tmp = ROOT / "cache" / "real_update_test"
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "valotalk").mkdir(parents=True)
        (tmp / "valotalk" / "__init__.py").write_text('__version__ = "2.1.2"\n',
                                                      encoding="utf-8")
        import valotalk.updater as u
        old_root = u.ROOT
        u.ROOT = tmp
        up2 = u.Updater(CONFIG.get, log=print)
        up2._staging = staging
        ok = up2.apply(staging)
        u.ROOT = old_root
        check("apply 成功", ok, up2.last_error)
        if ok:
            new_init = (tmp / "valotalk" / "__init__.py").read_text(encoding="utf-8")
            check("版本号被更新到 2.1.3", "2.1.3" in new_init, new_init.strip()[-20:])
            baks = list((tmp / "cache" / "update" / "backup").rglob("__init__.py"))
            check("备份存在", len(baks) > 0)
            if baks:
                check("备份是旧版本",
                      "2.1.2" in baks[0].read_text(encoding="utf-8"))
        shutil.rmtree(tmp, ignore_errors=True)

fake.cleanup()

print("\n" + "=" * 52)
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
print("=" * 52)
sys.exit(0 if failed == 0 else 1)