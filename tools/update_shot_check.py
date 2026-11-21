"""检查更新弹窗截图是否正常渲染（尺寸 + 色彩数，判断不是空白/纯色）。"""
from __future__ import annotations
import os
from pathlib import Path

import numpy as np
from PIL import Image

CACHE = Path(__file__).resolve().parent.parent / "cache"
FILES = ["update_dialog.png", "update_1_initial.png",
         "update_2_downloading.png", "update_3_done.png"]

for name in FILES:
    p = CACHE / name
    if not p.exists():
        print(f"{name:30s} 缺失")
        continue
    im = Image.open(p).convert("RGB")
    a = np.asarray(im)
    colors = len(np.unique(a.reshape(-1, 3), axis=0))
    dark = float((a.sum(axis=2) < 90).mean())
    print(f"{name:30s} {im.size}  唯一色={colors:6d}  暗色占比={dark:.2f}")

# 进度条截图里蓝色像素应该明显多于初始状态
def blue_ratio(p):
    a = np.asarray(Image.open(p).convert("RGB")).astype(int)
    # ui.BLUE = #0A84FF
    m = (abs(a[:,:,0]-10) < 40) & (abs(a[:,:,1]-132) < 50) & (abs(a[:,:,2]-255) < 40)
    return float(m.mean())

b1 = blue_ratio(CACHE / "update_1_initial.png")
b2 = blue_ratio(CACHE / "update_2_downloading.png")
b3 = blue_ratio(CACHE / "update_3_done.png")
print()
print(f"蓝色像素占比  初始={b1:.4f}  下载中={b2:.4f}  完成={b3:.4f}")
print(f"  下载中比初始多（进度条出现）: {b2 > b1}")
print(f"  完成时仍有多余蓝色（按钮/进度条）: {b3 > b1}")