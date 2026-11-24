"""验证线上的自愈下载目标是否真的可用。

自愈用的是 jsdelivr：
  1) https://cdn.jsdelivr.net/gh/LinDS-9A/ValoTalk@v3.0.0-beta/valotalk/xxx.py
  2) https://cdn.jsdelivr.net/gh/LinDS-9A/ValoTalk@main/valotalk/xxx.py
这里两个都试，并和本地文件逐字节比对。
"""
from __future__ import annotations
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO = "LinDS-9A/ValoTalk"
BASE = f"https://cdn.jsdelivr.net/gh/{REPO}"
TAG = "v3.0.0-beta"
LOCAL = Path(__file__).resolve().parent.parent

TARGETS = [
    ("valotalk/profiles.py", "valotalk/profiles.py"),
    ("valotalk/envcheck.py", "valotalk/envcheck.py"),
]


def fetch(url: str, timeout: float = 25.0) -> bytes | None:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ValoTalk-Bootstrap/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        print(f"      失败: {type(e).__name__}: {str(e)[:70]}")
        return None


print("=" * 60)
print("验证自愈下载目标")
print("=" * 60)

ok_all = True
for rel, local_rel in TARGETS:
    print(f"\n[{rel}]")
    local = (LOCAL / local_rel).read_bytes()
    got = None
    for url in (f"{BASE}@{TAG}/{rel}", f"{BASE}@main/{rel}"):
        short = url.replace(BASE, "…")
        print(f"    试 {short}")
        data = fetch(url)
        if data and len(data) > 300:
            print(f"      → {len(data)} 字节")
            got = data
            break
        print(f"      → 不可用")
    if got is None:
        print("    ✗ 两个源都拿不到")
        ok_all = False
        continue
    if got == local:
        print(f"    ✓ 与本地完全一致（{len(local)} 字节）")
    else:
        print(f"    ⚠ 大小 线上 {len(got)} / 本地 {len(local)}")
        # 可能是行尾差异
        if got.replace(b"\r\n", b"\n") == local.replace(b"\r\n", b"\n"):
            print("       （只差行尾符，内容一致）")
        else:
            print("       !! 内容真的不同")
            ok_all = False

# 顺带验证 __init__.py 里的版本号在线上也对
print(f"\n[valotalk/__init__.py 的版本号]")
data = fetch(f"{BASE}@{TAG}/valotalk/__init__.py")
if data:
    for line in data.decode("utf-8", "ignore").splitlines():
        if line.startswith("__version__"):
            print(f"    线上: {line.strip()}")
            break
else:
    print("    ✗ 取不到")
    ok_all = False

print("\n" + "=" * 60)
print("自愈下载链路可用 ✅" if ok_all else "自愈下载链路有问题 ❌")
print("=" * 60)
sys.exit(0 if ok_all else 1)
