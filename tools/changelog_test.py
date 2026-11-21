"""验证 CHANGELOG.md 的版本段落能被 updater 正确解析（弹窗里的更新说明靠它）。"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

print("CHANGELOG 版本段落解析:")
ok = True
for ver, expect_nonempty in [("2.1.3", True), ("2.1.2", True),
                             ("2.1.0", True), ("2.0.0", True),
                             ("9.9.9", False)]:
    pat = re.compile(rf"^##\s*v?{re.escape(ver)}\b.*?$(.*?)(?=^##\s|\Z)",
                     re.M | re.S)
    m = pat.search(text)
    body = m.group(1).strip() if m else ""
    good = bool(body) == expect_nonempty
    ok &= good
    first = body.splitlines()[0][:46] if body else "（空，符合预期）"
    print(f"  [{'PASS' if good else 'FAIL'}] v{ver}: {len(body)} 字符  {first}")

# 版本段落不能互相串味
pat213 = re.compile(r"^##\s*v?2\.1\.3\b.*?$(.*?)(?=^##\s|\Z)", re.M | re.S)
b = pat213.search(text).group(1)
print(f"\nv2.1.3 段落是否只含 2.1.3 的内容: {'自动更新' in b}")
print(f"  是否误含 2.1.2 内容: {'鬼畜音' in b}")

print("\n" + ("全部通过 ✅" if ok else "有失败 ❌"))
sys.exit(0 if ok else 1)