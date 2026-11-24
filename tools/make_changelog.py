"""把 CHANGELOG 的「未发布」段落改写成 v3.0.0-beta，并追加本轮改动。"""
from __future__ import annotations
import io
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
lines = io.open(P, encoding="utf-8").read().splitlines(keepends=True)

# 找到「未发布」段落范围
start = None
end = None
for i, l in enumerate(lines):
    if l.startswith("## 未发布"):
        start = i
    elif start is not None and l.startswith("## "):
        end = i
        break
if start is None:
    raise SystemExit("找不到「未发布」段落")

old_body = "".join(lines[start + 1:end])

new_head = """## v3.0.0-beta

> ⚠️ **这是测试版**，界面和功能还在调整。更新时会自动备份到
> `cache/update/backup/`，想回退就从 Releases 下载上一个正式版覆盖。

**界面换成浅色液态玻璃**

- 整个窗口做成「壁纸铺底 + 一堆半透明玻璃卡片浮在上面」：
  背景单独一层，卡片/顶栏/dock 都是毛玻璃，能透出背后的壁纸
- 真毛玻璃：背景先做高斯模糊再叠白，文字不会被壁纸纹理干扰
  （先缩到 1/4 再模糊再放大，计算量降到 1/16）
- 卡片超透明（白色只叠 32%），日志区用 Canvas 自绘 ——
  文字和玻璃画在同一层，能透过字看到背后图案
- 大 R 角：系统圆角改不了半径，改用 `SetWindowRgn` 自己裁窗口（22px）

**去掉系统标题栏**

- 客户区顶到窗口最上沿，原来的顶栏变成真正的标题栏
- 自己画最小化 / 最大化 / 关闭（关闭键悬停变红），顶栏可拖动、双击最大化
- 最大化按「可用区域」算，不盖任务栏

**修掉的几个坑**

- 圆角处的黑角：`round_image` / `glass_image` 生成的图片圆角外是
  `alpha=0`，Tk 的 Canvas 不做 alpha 合成、直接画成黑色。现在圆角外
  一律填充调用方的实际底色（开关、按钮、下拉框、dock 都受影响）
- dock 左右露出蓝带：外层容器用了壁纸原色，和周围的灰玻璃差一层
- 卡片内容溢出被裁：日志区把滚动条整条去掉了，改成内容超高才出现的细条
- 最大化卡死：4:3 锁定和最大化互相拉扯（Configure → geometry → 循环）

**老版本更新上来不会崩（重要）**

v2.3.0 的更新清单里没有 `profiles.py` / `envcheck.py` / `assets/`，
老用户更新时会漏下这些文件、启动直接 ImportError。现在
`valotalk/__init__.py` 会在子模块被 import 之前自检，缺了就从 CDN
补齐；网络不通则写一份降级实现保证能启动（模型列表为空，可手动重加），
下次启动还会继续重试直到拿到正式版。

**其它**

- 关于页加赞助码（点图片看原尺寸大图）
- 标题栏和关于页都挂「测试版」橙标，点一下说明风险和回退方法
- 更新弹窗对 beta 版本额外显示提示条
- 更新清单补全到 24 个文件（之前漏了 4 个）

"""

# 保留原来「未发布」里的内容（那些改动确实在这个版本里）
new_text = new_head + old_body.rstrip() + "\n\n"

out = "".join(lines[:start]) + new_text + "".join(lines[end:])
io.open(P, "w", encoding="utf-8", newline="\n").write(out)
print(f"改写完成：原「未发布」段落 {end - start - 1} 行，保留并归入 v3.0.0-beta")
