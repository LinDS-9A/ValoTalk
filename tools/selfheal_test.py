"""验证老版本更新上来的自愈路径。

做法：把 profiles.py / envcheck.py 临时挪走，再 import app，
看 __init__ 的 _self_heal() 能不能补齐、App 能不能构建。
"""
from __future__ import annotations
import os
import shutil
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "valotalk"
BACKUP = PKG.parent / "cache" / "_heal_backup"

print("=" * 56)
print("模拟：v2.3.0 更新上来后缺 profiles.py / envcheck.py")
print("=" * 56)

BACKUP.mkdir(parents=True, exist_ok=True)
moved = []
for name in ("profiles.py", "envcheck.py"):
    src = PKG / name
    if src.exists():
        shutil.move(str(src), str(BACKUP / name))
        moved.append(name)
        print(f"  已移除 {name}")

# 清掉可能存在的 pyc，确保走真实 import
for d in (PKG / "__pycache__",):
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)

sys.path.insert(0, str(PKG.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

ok = False
try:
    t0 = time.time()
    import valotalk  # noqa: F401  ← 触发 _self_heal()
    print(f"\n__init__ 自愈耗时 {time.time()-t0:.2f}s")

    for name in moved:
        p = PKG / name
        if p.exists():
            size = p.stat().st_size
            head = p.read_text(encoding="utf-8", errors="replace")[:60]
            kind = "下载的正式版" if "降级版" not in head else "降级实现"
            print(f"  {name}: 已生成 {size} 字节（{kind}）")
        else:
            print(f"  {name}: ✗ 没生成")

    print("\n尝试 import app …")
    from valotalk.app import App
    print("  import 成功 ✓")

    from _cfg_guard import config_guard
    with config_guard():
        a = App()
        a._running = True
        for _ in range(18):
            a.root.update()
            time.sleep(0.06)
        print(f"  界面构建成功 ✓  窗口 {a.root.winfo_width()}x{a.root.winfo_height()}")
        a.shutdown()
    ok = True
except Exception:
    import traceback
    print("\n失败：")
    traceback.print_exc()
finally:
    # 还原真实文件
    for name in moved:
        dst = PKG / name
        src = BACKUP / name
        if src.exists():
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))
    print("\n已还原原始文件")

print("\n" + "=" * 56)
print("自愈路径可用 ✅" if ok else "自愈路径失败 ❌")
print("=" * 56)
sys.exit(0 if ok else 1)