"""检查 updater.UPDATE_FILES 是否覆盖了 valotalk/ 下所有模块。

自动更新靠这个清单决定下载哪些文件 —— 漏一个，更新后程序就起不来
（这次就漏过 asr_cloud.py）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from valotalk import updater

pkg = ROOT / "valotalk"
actual = sorted(p.name for p in pkg.glob("*.py")
                if p.name not in ("__pycache__",))
listed = {Path(f).name for f in updater.UPDATE_FILES if f.startswith("valotalk/")}

missing = [n for n in actual if n not in listed]
extra = sorted(listed - set(actual))

print(f"valotalk/ 下共 {len(actual)} 个 .py：")
for n in actual:
    print(f"  {'✓' if n in listed else '✗ 未列入'} {n}")

if extra:
    print(f"\n清单里多出的（文件不存在）：{extra}")
if missing:
    print(f"\n✗ 漏列了 {len(missing)} 个：{missing}")
    print("  自动更新会缺这些文件，必须补进 updater.UPDATE_FILES")
    sys.exit(1)

print("\n✓ UPDATE_FILES 覆盖完整")
sys.exit(0)