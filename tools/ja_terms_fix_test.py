"""验证日语术语纠正不会误伤。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valotalk.asr_cloud import fix_ja_terms

CASES = [
    # (输入, 期望)
    ("売ると使うからカバー して。", "ウルト使うからカバー して。"),
    ("売ると準備できてる。", "ウルト準備できてる。"),
    ("スポイク設置した。", "スパイク設置した。"),
    ("エコだから慎重に。", "エコーだから慎重に。"),
    ("エコーだから慎重に。", "エコーだから慎重に。"),      # 已经是エコー，别变成エコーー
    ("ろーてーとして。", "ローテートして。"),
    ("ロテートしよう。", "ローテートしよう。"),
    ("オペレタ持ってる。", "オペレーター持ってる。"),
    ("プランクに注意。", "フランクに注意。"),
    # 不该动的
    ("Aサイトに敵、フランクに注意。", "Aサイトに敵、フランクに注意。"),
    ("残り hp少ない、詰めて。", "残り hp少ない、詰めて。"),
    ("", ""),
    ("普通の日本語です。", "普通の日本語です。"),
]

failed = 0
for src, expect in CASES:
    got = fix_ja_terms(src)
    ok = got == expect
    if not ok:
        failed += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {src!r}")
    if not ok:
        print(f"         期望 {expect!r}")
        print(f"         实际 {got!r}")

print()
print("全部通过 ✅" if failed == 0 else f"失败 {failed} 项 ❌")
sys.exit(0 if failed == 0 else 1)