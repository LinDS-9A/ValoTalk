"""验证不同字号确实渲染出不同大小的文字（靠非透明像素的包围盒判断）。"""
from __future__ import annotations
from pathlib import Path

import numpy as np
from PIL import Image

CACHE = Path(__file__).resolve().parent.parent / "cache"
FILES = [("sub_small.png", 14), ("sub_mid.png", 19), ("sub_big.png", 30)]

print("字幕窗截图分析（colorkey #010203 是透明区域）:")
prev_h = 0
ok = True
for name, size in FILES:
    p = CACHE / name
    if not p.exists():
        print(f"  {name} 缺失")
        ok = False
        continue
    a = np.asarray(Image.open(p).convert("RGB")).astype(int)
    # 透明键 #010203 以外的像素 = 有内容
    key = (abs(a[:, :, 0] - 1) < 6) & (abs(a[:, :, 1] - 2) < 6) & (abs(a[:, :, 2] - 3) < 6)
    content = ~key
    rows = np.where(content.any(axis=1))[0]
    cols = np.where(content.any(axis=0))[0]
    if rows.size == 0:
        print(f"  {name}: 没有内容")
        ok = False
        continue
    h = rows.max() - rows.min() + 1
    w = cols.max() - cols.min() + 1
    px = int(content.sum())
    print(f"  字号 {size:2d}: 文字区 {w}x{h}  非透明像素 {px}")
    if prev_h and h <= prev_h:
        print(f"    ✗ 没有比上一档更大")
        ok = False
    prev_h = h

print()
print("字号越大文字区越高 ✅" if ok else "字号没生效 ❌")