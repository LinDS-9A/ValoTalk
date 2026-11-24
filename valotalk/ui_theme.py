"""iOS 风格圆角控件库（tkinter + Pillow）。

tkinter 没有原生圆角，这里用 PIL 渲染抗锯齿的圆角图当背景，
控件内容叠在 Canvas 上。配色用 iOS 深色模式那套。
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageTk

# ---------------- 浅色液态玻璃配色 ----------------
# 参考的观感：白色半透明玻璃浮在壁纸上，文字用深灰，靠明暗分层不靠描边。
# tk 控件无法真正透明，圆角外露的都是 BG —— 所以 BG 取壁纸压暗后的近似值，
# 让露出来的角落不显眼。玻璃层用白色叠加，背景图从下面透出来。
BG = "#DCDCE2"          # 窗口底色 / 补齐色（壁纸压暗后的近似值）
BG2 = "#DCDCE2"         # 与 BG 同值：保留变量名兼容
PANEL = "#C6C6D0"       # 玻璃层叠的颜色（灰调，让白卡片能从背景里浮出来）
# 标题栏区域的等效底色。tk 的 Label/按钮不能透明，只能用固定色近似它下面
# 那层毛玻璃的观感（壁纸顶部经模糊 + 白 0.42 叠加后约 #F5F5F7）。
# 换背景图或改 head 的 layers 权重时要跟着重采，否则头上一块白会跳出来。
HEAD_BG = "#F6F6F8"
CARD = "#FFFFFF"        # 卡片材质：纯白，叠在半透明白玻璃上才浮得出来
# CARD_TOP / CARD_BOT 只出现在卡片边缘一圈的窄过渡带里，不进内容区。
# 浅色下明度差要更小，不然边缘像贴了双面胶。
CARD_TOP = "#FFFFFF"    # 边缘上端（受光）
CARD_BOT = "#EDEDF1"    # 边缘下端（微暗）
CARD2 = "#F7F7F9"       # 二级玻璃 / 输入框（比卡片略灰，凹进去）
CARD3 = "#E2E2E8"       # 三级 / hover
SEP = "#DFDFE5"         # 分隔线
GLASS_EDGE = "#FFFFFF"  # 边缘亮线（低透明度叠上去）
GLASS_TOP = "#FFFFFF"   # 顶部高光
TEXT = "#1D1D1F"        # 主文字（近黑，不用纯黑）
TEXT2 = "#5C5C66"       # 次要文字
TEXT3 = "#8E8E99"       # 更弱
BLUE = "#0A7CFF"        # 主色（浅底上用饱和一点的蓝）
GREEN = "#17A34A"       # 开关开
RED = "#E5484D"
YELLOW = "#E8A600"
ORANGE = "#E8760A"

FONT = "Microsoft YaHei UI"
FS = 10                 # 正文字号
FS_SMALL = 9
FS_TITLE = 15

CARD_RADIUS = 18        # 大圆角，但不至于像药丸
BTN_RADIUS = 11
PILL_RADIUS = 20
# 窗口本身的圆角。要真正的大 R 角必须用 SetWindowRgn 裁窗口 ——
# DWM 的 DWMWCP_ROUND 是固定的系统圆角（约 8px），改不了。
WIN_RADIUS = 22

_img_cache: dict[tuple, ImageTk.PhotoImage] = {}


def _mix(c1: str, c2: str, f: float) -> tuple[int, int, int]:
    """两个颜色按 f 线性插值。"""
    a = ImageColor.getrgb(c1)
    b = ImageColor.getrgb(c2)
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


def round_image(w: int, h: int, radius: int, color: str,
                outline: str | None = None, width: int = 1,
                outside: str | None = None) -> ImageTk.PhotoImage:
    """生成抗锯齿圆角矩形，带缓存。

    outside: 圆角外填充色。⚠️ 不要留空 —— Tk 的 Canvas 会把 RGBA 里
    alpha=0 的像素**画成黑色**，这就是圆角处那四个「黑角」。传父容器的
    实际底色即可（开关、按钮这类小控件传自己所在的卡片色）。
    """
    w, h = max(1, int(w)), max(1, int(h))
    radius = max(0, min(int(radius), min(w, h) // 2))
    key = (w, h, radius, color, outline, width, outside)
    cached = _img_cache.get(key)
    if cached is not None:
        return cached
    scale = 4                                   # 超采样再缩小，边缘更干净
    base = (ImageColor.getrgb(outside) + (255,)) if outside else (0, 0, 0, 0)
    img = Image.new("RGBA", (w * scale, h * scale), base)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (0, 0, w * scale - 1, h * scale - 1),
        radius=radius * scale,
        fill=color,
        outline=outline,
        width=width * scale if outline else 0,
    )
    img = img.resize((w, h), Image.LANCZOS)
    photo = ImageTk.PhotoImage(img)
    if len(_img_cache) > 400:                   # 别无限涨
        _img_cache.clear()
    _img_cache[key] = photo
    return photo


def glass_image(w: int, h: int, radius: int,
                top: str = CARD_TOP, bottom: str = CARD_BOT,
                edge: float = 0.36, highlight: float = 0.50,
                inner_shadow: float = 0.42, mid: str | None = None,
                edge_pad: int = 0,
                fill: str | None = None,
                outside_color: str | None = None) -> ImageTk.PhotoImage:
    """液态玻璃底图：均匀材质 + 边缘渐变 + 顶部高光 + 外描边 + 底部内阴影。

    - top/bottom：边缘渐变两端。上亮下暗，模拟上方光源。
    - mid + edge_pad：**内部保持均匀材质色**，只在边缘一圈做渐变。
      卡片里嵌 Frame 时必须用它 —— 内部 Frame 与 mid 完全同色，
      无缝无分界，玻璃感只由边缘光感承担。edge_pad 是边缘过渡带的
      逻辑像素高度。edge_pad=0 时全范围渐变（按钮/输入框等无内嵌
      容器的小控件用它）。
    - edge：外描边白色透明度。勾一圈极细亮线，玻璃才有「厚度」。
    - highlight：顶部内侧高光。沿上边缘扫一道亮弧，像光打在玻璃上。
    - inner_shadow：底部内侧暗影。让下边缘「陷进去」，卡片才有体积。
    - fill：给了就跳过渐变，用单色（兼容旧调用）。
    """
    w, h = max(1, int(w)), max(1, int(h))
    radius = max(0, min(int(radius), min(w, h) // 2))
    key = ("glass", w, h, radius, top, bottom, edge, highlight,
           inner_shadow, mid, edge_pad, fill, outside_color)
    cached = _img_cache.get(key)
    if cached is not None:
        return cached

    S = 3                                        # 超采样倍数
    W, H = w * S, h * S
    R = radius * S
    mid_c = mid or CARD

    # 1) 渐变主体
    if fill:
        base = Image.new("RGBA", (W, H), ImageColor.getrgb(fill) + (255,))
    else:
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(base)
        if edge_pad > 0:
            # 只在上下边缘做渐变，中间钉死在 mid —— 和内部 Frame 完全同色。
            # smoothstep（3t²-2t³）两端导数为 0，过渡带与纯色区衔接处
            # 没有任何跳变，肉眼看不到接缝，这是不出现「阶梯」的关键。
            pad_px = max(2, int(edge_pad * S))
            pad_bot = max(2, int(edge_pad * S * 1.4))     # 底部稍厚
            mid_rgb = ImageColor.getrgb(mid_c)
            for y in range(H):
                if y < pad_px:
                    t = y / pad_px
                    t = t * t * (3 - 2 * t)
                    c = _mix(top, mid_c, t)
                elif y > H - pad_bot:
                    t = (y - (H - pad_bot)) / pad_bot
                    t = t * t * (3 - 2 * t)
                    c = _mix(mid_c, bottom, t)
                else:
                    c = mid_rgb
                d.line([(0, y), (W, y)], fill=c + (255,))
        else:
            # 全范围渐变：前 45% 快速变暗，之后平缓，更像真实玻璃受光
            for y in range(H):
                f = y / max(1, H - 1)
                e = min(1.0, (f / 0.45) ** 0.65) if f < 0.45 else \
                    min(1.0, 1.0 + (f - 0.45) * 0.5)
                c = _mix(top, bottom, e)
                d.line([(0, y), (W, y)], fill=c + (255,))

    # 2) 用圆角矩形做遮罩，裁出卡片形状
    # 圆角外必须填底色：alpha=0 的像素在 Tk Canvas 上会画成黑色（黑角）
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1),
                                           radius=R, fill=255)
    outside_rgb = (ImageColor.getrgb(outside_color)
                   if outside_color else ImageColor.getrgb(BG))
    img = Image.new("RGBA", (W, H), outside_rgb + (255,))
    img.paste(base, (0, 0), mask)

    # 3) 顶部高光：紧贴顶边、快速衰减的窄白层（宽了就成银色边框）
    if highlight > 0 and H > 6:
        band_h = max(2, H // 10)
        hi = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dh = ImageDraw.Draw(hi)
        for y in range(band_h):
            a = int(255 * highlight * (1 - y / band_h) ** 2)
            if a <= 0:
                continue
            dh.line([(0, y), (W, y)], fill=(255, 255, 255, a))
        img = Image.alpha_composite(img, Image.composite(
            hi, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask))

    # 4) 底部内阴影：下边缘「陷进去」，卡片才有体积
    if inner_shadow > 0 and H > 10:
        band = max(3, H // 5)
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ds = ImageDraw.Draw(sh)
        for y in range(band):
            a = int(255 * inner_shadow * (y / band) ** 2)
            if a <= 0:
                continue
            yy = H - 1 - y
            ds.line([(0, yy), (W, yy)], fill=(0, 0, 0, a))
        img = Image.alpha_composite(img, Image.composite(
            sh, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask))

    # 5) 外描边：极细一圈亮线
    if edge > 0:
        a = int(255 * edge)
        ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle(
            (0, 0, W - 1, H - 1), radius=R,
            outline=(255, 255, 255, a), width=max(1, int(S * 1.1)))
        img = Image.alpha_composite(img, ring)

    img = img.resize((w, h), Image.LANCZOS)
    photo = ImageTk.PhotoImage(img)
    if len(_img_cache) > 400:
        _img_cache.clear()
    _img_cache[key] = photo
    return photo


# ---------------------------------------------------------------- 背景图
_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_bg_source: Image.Image | None = None
# 缩放后的整张背景图缓存：(win_w, win_h) → Image
# 为什么要缓存：13 个 pane 各自调一次 bg_image，每次都对整图做 LANCZOS 缩放，
# 最大化到 2560×1440 时一次就是几百毫秒 ×13，界面直接冻住。
_bg_scaled: dict[tuple[int, int], Image.Image] = {}


# 背景图压暗系数（0 = 原图，1 = 全黑）
# 浅色玻璃要透出壁纸，所以几乎不压暗，只稍微降一点饱和/亮度避免抢内容。
BG_DIM = 0.12
_BG_DIM_COLOR = (236, 236, 242)


def load_bg_source() -> Image.Image:
    """加载并缓存背景原图（4:3），按 BG_DIM 压暗。

    背景图缺失时（老版本更新上来、assets 没跟着下来的情况）不能让
    Image.open 抛异常 —— 整条渲染链会断掉、界面直接白屏。这里降级成
    一张纯色底，界面照样能用，只是没有壁纸。
    """
    global _bg_source
    if _bg_source is None:
        try:
            im = Image.open(
                os.path.join(_ASSET_DIR, "bg.png")).convert("RGB")
        except Exception:
            im = Image.new("RGB", (1024, 768), (232, 232, 238))
        if BG_DIM > 0:
            dark = Image.new("RGB", im.size, _BG_DIM_COLOR)
            im = Image.blend(im, dark, min(1.0, max(0.0, BG_DIM)))
        _bg_source = im
    return _bg_source


def card_inner_color(w: int, h: int, rx: int, ry: int,
                     win_w: int, win_h: int,
                     layers: tuple[tuple[str, float], ...] | None = None,
                     blur: float = 5.0) -> str:
    """算出一块玻璃面板「正中间」的实际渲染色。

    干什么用：tk 的 Text/Entry/Label 都不能透明，只能给个固定底色。
    玻璃已经模糊过了，本来就只剩色调没有细节 —— 只要内部控件的底色
    等于这块玻璃的实际色，视觉上就是「透」的，不会出现一块白板。

    注意每块面板后面的壁纸颜色不同（日志卡偏冷 #EDF1F3、左列偏暖 #F8F3F2），
    所以必须**逐块算**，不能全局用一个常量。
    """
    w, h = max(1, int(w)), max(1, int(h))
    win_w, win_h = max(1, int(win_w)), max(1, int(win_h))
    cx = min(win_w - 1, max(0, int(rx) + w // 2))
    cy = min(win_h - 1, max(0, int(ry) + h // 2))
    try:
        # 取中心附近一小块求平均（模糊后本来就均匀，取平均更稳）
        half = max(2, min(12, w // 8, h // 8))
        full = _scaled_bg(win_w, win_h)
        box = (max(0, cx - half), max(0, cy - half),
               min(win_w, cx + half), min(win_h, cy + half))
        patch = full.crop(box)
        if blur > 0:
            try:
                k = 4
                sw = max(1, patch.width // k)
                sh = max(1, patch.height // k)
                patch = patch.resize((sw, sh), Image.BILINEAR)
                patch = patch.filter(
                    ImageFilter.GaussianBlur(max(0.5, blur / k)))
                patch = patch.resize((box[2] - box[0], box[3] - box[1]),
                                     Image.BILINEAR)
            except Exception:
                pass
        px = patch.resize((1, 1), Image.BOX).getpixel((0, 0))
    except Exception:
        px = ImageColor.getrgb(BG)
    if layers is None:
        layers = CARD_LAYERS
    # 注意：_mix() 只接受十六进制字符串，这里 px 是 RGB 元组，得手算
    r, g, b = float(px[0]), float(px[1]), float(px[2])
    for color, alpha in layers:
        cr, cg, cb = ImageColor.getrgb(color)
        a = float(alpha)
        r = r * (1 - a) + cr * a
        g = g * (1 - a) + cg * a
        b = b * (1 - a) + cb * a
    return "#%02X%02X%02X" % (int(round(r)), int(round(g)), int(round(b)))


def bg_gradient(w: int, h: int) -> ImageTk.PhotoImage:
    """整张背景图缩放到 w×h（窗口固定 4:3，与原图同比例，不变形）。

    保留旧函数名以兼容底层画布调用。
    """
    return bg_image(w, h, 0, 0, w, h)


def _scaled_bg(win_w: int, win_h: int) -> Image.Image:
    """整张背景图缩放到窗口尺寸，按尺寸缓存（这是最贵的一步）。"""
    key = (win_w, win_h)
    hit = _bg_scaled.get(key)
    if hit is not None:
        return hit
    # BILINEAR 比 LANCZOS 快 3~4 倍，尺寸差这么大肉眼分不出区别
    img = load_bg_source().resize((win_w, win_h), Image.BILINEAR)
    if len(_bg_scaled) > 12:                       # 只留最近几档尺寸
        _bg_scaled.clear()
    _bg_scaled[key] = img
    return img


def bg_image(w: int, h: int, rx: int, ry: int,
             win_w: int, win_h: int) -> ImageTk.PhotoImage:
    """背景图在顶层窗口 (rx,ry) 处 w×h 的裁剪块。

    先把原图缩放到整个顶层窗口尺寸，再按该 pane 的绝对位置裁剪，
    于是任意多层 pane 拼起来都是完整的一张背景图，不会重复或错位。
    """
    w, h = max(1, int(w)), max(1, int(h))
    win_w, win_h = max(1, int(win_w)), max(1, int(win_h))
    rx, ry = max(0, int(rx)), max(0, int(ry))
    key = ("bgimg", w, h, rx, ry, win_w, win_h)
    cached = _img_cache.get(key)
    if cached is not None:
        return cached
    full = _scaled_bg(win_w, win_h)
    crop = full.crop((rx, ry, min(win_w, rx + w), min(win_h, ry + h)))
    if crop.size != (w, h):                      # 贴边时补齐
        pad = Image.new("RGB", (w, h), BG)
        pad.paste(crop, (0, 0))
        crop = pad
    photo = ImageTk.PhotoImage(crop)
    if len(_img_cache) > 400:
        _img_cache.clear()
    _img_cache[key] = photo
    return photo


# 大面板半透明玻璃的默认叠层（颜色, 不透明度）
PANEL_LAYERS = ((PANEL, 0.62),)

# 透明卡片叠层：在大面板玻璃之上再叠一层很轻的 CARD，卡片比周围玻璃
# 略「实」一点、边界清楚，但背景图依然透过卡片可见。数值越小越透。
# 卡片：只叠薄薄一层白，壁纸从下面清晰透出来（超透明玻璃）。
# 权重太高会变成实心白板，太低文字会和背景细节打架 —— 0.32 是可读性下限。
CARD_LAYERS = ((CARD, 0.32),)

_eq_cache: dict[tuple, str] = {}


def glass_equivalent_color(rx: int, ry: int, w: int, h: int,
                           win_w: int, win_h: int,
                           layers: tuple[tuple[str, float], ...]) -> str:
    """某矩形区域「背景图 + 玻璃叠层」合成后的平均固定色（hex）。

    tkinter 普通 Frame/Label 只能用纯色、无法真正透明。这里取该区域
    背景图的平均色，再按与 glass_over_bg 完全相同的顺序叠加玻璃层，
    得到与下方合成玻璃几乎一致的固定色，于是不透明控件也能「伪装」成
    半透明玻璃，整棵控件树拼回完整的一张透背景画面。
    """
    w, h = max(1, int(w)), max(1, int(h))
    win_w, win_h = max(1, int(win_w)), max(1, int(win_h))
    rx, ry = max(0, int(rx)), max(0, int(ry))
    lay_key = tuple((c, round(float(a), 4)) for c, a in layers)
    key = (rx, ry, w, h, win_w, win_h, lay_key)
    cached = _eq_cache.get(key)
    if cached is not None:
        return cached
    try:
        full = _scaled_bg(win_w, win_h)
        x0, y0 = max(0, rx), max(0, ry)
        x1, y1 = min(win_w, rx + w), min(win_h, ry + h)
        if x1 > x0 and y1 > y0:
            crop = full.crop((x0, y0, x1, y1)).convert("RGB")
            # 缩到 1x1（BOX 下采样）即该区域的平均色
            r, g, b = crop.resize((1, 1), Image.BOX).getpixel((0, 0))
        else:
            r, g, b = ImageColor.getrgb(BG)
        r, g, b = float(r), float(g), float(b)
        for color, alpha in layers:
            cr, cg, cb = ImageColor.getrgb(color)
            a = float(alpha)
            r = r * (1 - a) + cr * a
            g = g * (1 - a) + cg * a
            b = b * (1 - a) + cb * a
        out = "#%02X%02X%02X" % (int(round(r)), int(round(g)), int(round(b)))
    except Exception:
        out = CARD
    if len(_eq_cache) > 800:
        _eq_cache.clear()
    _eq_cache[key] = out
    return out


def glass_over_bg(w: int, h: int, rx: int, ry: int,
                  win_w: int, win_h: int, radius: int,
                  layers: tuple[tuple[str, float], ...] = PANEL_LAYERS,
                  edge: float = 0.0, highlight: float = 0.0,
                  scale: int = 2, keep_outside: bool = True,
                  edge_color: str = "#FFFFFF",
                  blur: float = 0.0,
                  outside_color: str | None = None,
                  outside_layers: tuple | None = None
                  ) -> ImageTk.PhotoImage:
    """背景图 + 若干半透明玻璃层叠，再裁圆角，返回 PhotoImage。

    每个容器都基于**原始背景图**重新合成属于自己的那一块（按相对顶层
    窗口的位置裁剪），于是无需真正的控件透明，多层容器也能拼回一整块
    半透明玻璃，背景图从玻璃下透出来。

    - layers：(颜色, 不透明度) 列表，自上而下依次 alpha 叠加。
    - edge：圆角外描边白色不透明度；highlight：顶部高光不透明度。
    - keep_outside：圆角外保留原始背景图（True，默认，永不出现黑色角）；
      False 时圆角外透明，露出 Canvas 底色。
    - scale：超采样倍数，缩小后圆角边缘抗锯齿。
    """
    w, h = max(1, int(w)), max(1, int(h))
    win_w, win_h = max(1, int(win_w)), max(1, int(win_h))
    rx, ry = max(0, int(rx)), max(0, int(ry))
    radius = max(0, min(int(radius), min(w, h) // 2))
    lay_key = tuple((c, round(float(a), 4)) for c, a in layers)
    key = ("govb", w, h, rx, ry, win_w, win_h, radius, lay_key,
           edge, highlight, scale, keep_outside, edge_color, blur,
           outside_color, outside_layers)
    cached = _img_cache.get(key)
    if cached is not None:
        return cached

    W, H, R = w * scale, h * scale, radius * scale
    full = _scaled_bg(win_w * scale, win_h * scale)
    # 控件在 full 坐标系里的左上 / 右下。窗口尚未 map 时顶层 winfo 可能
    # 只有 1x1，或控件瞬时超出窗口边缘 —— 直接 crop 会因 lower>upper 抛
    # ValueError，导致整层渲染中断、露出 Canvas 纯黑底。这里与 full 有效
    # 区求交集，缺失部分用 BG 兜底，保证任何输入都能安全返回一张图。
    fx0, fy0 = rx * scale, ry * scale
    fx1, fy1 = fx0 + W, fy0 + H
    ix0, iy0 = max(0, fx0), max(0, fy0)
    ix1, iy1 = min(full.width, fx1), min(full.height, fy1)
    if ix1 > ix0 and iy1 > iy0:
        crop = full.crop((ix0, iy0, ix1, iy1)).convert("RGBA")
    else:
        crop = None
    bg_only = Image.new("RGBA", (W, H),
                        ImageColor.getrgb(BG) + (255,))
    if crop is not None:
        # 毛玻璃：先把裁出来的背景块模糊，再叠白色。
        # 不模糊的话壁纸细节（线条、色块）会直接穿到文字底下，读不清；
        # 模糊后只留色调和大致形状，既透亮又干净。
        #
        # ⚡ 性能：直接对原尺寸做高斯模糊太贵（首帧从 0.9s 涨到 4s）。
        # 先缩到 1/4 再模糊、再放大回去 —— 视觉上等价（模糊本来就抹细节），
        # 计算量降到 1/16。半径也要按缩放比折算。
        if blur > 0:
            try:
                k = 4
                sw = max(1, W // k)
                sh = max(1, H // k)
                small = crop.resize((sw, sh), Image.BILINEAR)
                small = small.filter(
                    ImageFilter.GaussianBlur(max(0.5, blur * scale / k)))
                crop = small.resize((W, H), Image.BILINEAR)
            except Exception:
                pass
        bg_only.paste(crop, (ix0 - fx0, iy0 - fy0))

    glassed = bg_only
    for color, alpha in layers:
        layer = Image.new("RGBA", (W, H),
                          ImageColor.getrgb(color) + (int(255 * alpha),))
        glassed = Image.alpha_composite(glassed, layer)

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1),
                                           radius=R, fill=255)
    if keep_outside:
        # 圆角外保留「原始背景 + outside_layers」。
        # outside_layers 默认不叠（保持纯背景），传 PANEL_LAYERS 时圆角外
        # 就和父容器（普通玻璃面板）同色，圆角看不出接缝。
        out = bg_only
        if outside_layers:
            out = bg_only.copy()
            for color, alpha in outside_layers:
                lay = Image.new("RGBA", (W, H),
                                ImageColor.getrgb(color) + (int(255 * alpha),))
                out = Image.alpha_composite(out, lay)
        out = out.copy()
        out.paste(glassed, (0, 0), mask)
    else:
        # 圆角外不能用「透明」—— Tk 的 Canvas 会把 alpha=0 的像素画成黑色，
        # 就是用户看到的「四个黑角」。这里填成调用方指定的底色（通常是
        # 父容器的等效玻璃色），视觉上等于透明。
        base_rgb = ImageColor.getrgb(outside_color or BG)
        out = Image.new("RGBA", (W, H), base_rgb + (255,))
        out.paste(glassed, (0, 0), mask)

    if highlight > 0 and H > 6:
        band_h = max(2, H // 12)
        hi = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dh = ImageDraw.Draw(hi)
        for yy in range(band_h):
            a = int(255 * highlight * (1 - yy / band_h) ** 2)
            if a > 0:
                dh.line([(0, yy), (W, yy)], fill=(255, 255, 255, a))
        out = Image.alpha_composite(out, Image.composite(
            hi, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask))
    if edge > 0:
        ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle(
            (0, 0, W - 1, H - 1), radius=R,
            outline=ImageColor.getrgb(edge_color) + (int(255 * edge),),
            width=max(1, scale))
        out = Image.alpha_composite(out, ring)

    out = out.resize((w, h), Image.LANCZOS)
    photo = ImageTk.PhotoImage(out)
    if len(_img_cache) > 400:
        _img_cache.clear()
    _img_cache[key] = photo
    return photo


class GradientPane(tk.Canvas):
    """内容容器。模式：

    - 纯色（默认）：整幅 fill 色，独立弹窗或不透明容器用。
    - glass=True：半透明玻璃 —— 背景图 + layers 叠层，背景图从玻璃下透出。
    - image=True：只显示背景图属于自己的那一块（不叠玻璃色）。
    - panel=True：背景图打底 + 一块圆角纯色 fill，圆角外露出背景图。

    所有图片模式都按相对顶层窗口的位置裁剪，多层容器能拼回一整块。
    类名 / top / bottom 参数保留以兼容现有代码。
    """

    def __init__(self, master, top: str | None = None,
                 bottom: str | None = None, fill: str | None = None,
                 image: bool = False, panel: bool = False,
                 glass: bool = False, layers: tuple | None = None,
                 radius: int = CARD_RADIUS, edge: float = 0.0,
                 highlight: float = 0.0, blur: float = 0.0,
                 edge_color: str = '#FFFFFF', keep_outside: bool = True,
                 outside_color: str | None = None,
                 outside_layers: tuple | None = None, **kw):
        if glass:
            self._mode = "glass"
        elif image:
            self._mode = "image"
        elif panel:
            self._mode = "panel"
        else:
            self._mode = "solid"
        self._radius = radius
        self._fill = fill or PANEL
        self._layers = layers if layers is not None else PANEL_LAYERS
        self._edge = edge
        self._highlight = highlight
        self._blur = blur
        self._edge_color = edge_color
        self._keep_outside = keep_outside
        self._outside_color = outside_color
        self._outside_layers = outside_layers
        # glass 模式下 Canvas 底色用玻璃暗部色 PANEL：即使 DPI 取整导致
        # 边缘 1px 没被图片覆盖，露出的也是接近玻璃的暗部色，而非近黑接缝。
        if self._mode == "glass":
            canvas_bg = PANEL
        elif self._mode == "image":
            canvas_bg = BG
        else:
            canvas_bg = self._fill
        super().__init__(master, highlightthickness=0, bd=0,
                         bg=canvas_bg, **kw)
        self._img_id = None
        self._ph = None
        if self._mode != "solid":
            self.bind("<Configure>", self._paint)

    def _paint(self, _e=None) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        try:
            top = self.winfo_toplevel()
            win_w, win_h = top.winfo_width(), top.winfo_height()
            rx = self.winfo_rootx() - top.winfo_rootx()
            ry = self.winfo_rooty() - top.winfo_rooty()
            if self._mode == "glass":
                ph = glass_over_bg(w, h, rx, ry, win_w, win_h,
                                   self._radius, tuple(self._layers),
                                   edge=self._edge, highlight=self._highlight,
                                   blur=self._blur,
                                   edge_color=self._edge_color,
                                   keep_outside=self._keep_outside,
                                   outside_color=self._outside_color,
                                   outside_layers=self._outside_layers)
            elif self._mode == "image":
                ph = bg_image(w, h, rx, ry, win_w, win_h)
            else:  # panel：完全不透明的圆角 fill，圆角外露出背景图
                ph = glass_over_bg(w, h, rx, ry, win_w, win_h,
                                   self._radius,
                                   ((self._fill, 1.0),))
        except Exception:
            return
        self._ph = ph
        if self._img_id is not None:
            self.delete(self._img_id)
        self._img_id = self.create_image(0, 0, anchor="nw", image=ph)
        self.tag_lower(self._img_id)


def glass_color_at(f: float, top: str = CARD_TOP,
                   bottom: str = CARD_BOT) -> str:
    """[已废弃] 旧阶梯着色用的取色函数，新玻璃材质不再逐行取色。

    保留仅为兼容可能的外部调用，内部统一走 RoundCard.tint()。
    """
    f = max(0.0, min(1.0, float(f)))
    c = _mix(top, bottom, f)
    return "#%02X%02X%02X" % c


class RoundCard(tk.Canvas):
    """圆角卡片容器。子控件放进 .body。"""

    def __init__(self, master, radius: int = CARD_RADIUS, fill: str = CARD,
                 pad: int = 0, glass: bool = True, bottom_band: int = 0,
                 bg: str = BG, **kw):
        super().__init__(master, highlightthickness=0, bd=0, bg=bg, **kw)
        self.radius = radius
        self.fill = fill
        self.pad = pad
        self.glass = glass
        # 底部留一条不铺 body 的带子，露出玻璃渐变 —— 卡片才有「厚度」
        self.bottom_band = bottom_band if glass else 0
        # body 用渲染「含真实背景玻璃」的容器（GradientPane），而非纯色
        # Frame，背景图案才能透过卡片内部显示；它是直角、缩进在圆角内，
        # 不会破坏卡片圆角。
        self.body = GradientPane(self, glass=True, radius=0, layers=CARD_LAYERS)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.body)
        self._bg_id = None
        self._base_id = None
        self._autosize = True
        self.bind("<Configure>", self._redraw)
        self.body.bind("<Configure>", self._sync_height)

    def _cur_height(self) -> int:
        """当前请求高度（像素）。

        ⚠️ Tk 的 Canvas 默认 height 是字符串 "7c"（7 厘米），直接 int() 会抛
        ValueError: invalid literal for int() with base 10: '7c' ——
        内容第一次 Configure 时就会踩到，日志里刷一屏 Tkinter 回调异常。
        """
        try:
            return int(float(self["height"]))
        except Exception:
            try:
                return int(self.winfo_reqheight())
            except Exception:
                return 0

    def _sync_height(self, _event=None) -> None:
        """让画布高度跟着内容走，不用手写固定尺寸。"""
        if not self._autosize:
            return
        need = (self.body.winfo_reqheight() + self.pad * 2
                + self.bottom_band)
        if abs(need - self._cur_height()) > 2:
            self.configure(height=need)
            # 高度变了，每个子控件的纵向位置都变了 → 重新着色
            try:
                self.after_idle(self.tint)
            except Exception:
                pass

    def _redraw(self, event=None) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        try:
            top = self.winfo_toplevel()
            win_w, win_h = top.winfo_width(), top.winfo_height()
            rx = self.winfo_rootx() - top.winfo_rootx()
            ry = self.winfo_rooty() - top.winfo_rooty()
        except Exception:
            win_w, win_h, rx, ry = w, h, 0, 0

        # 底层：半透明面板背景（直角铺满），卡片圆角外的四角也显示它，
        # 透出背景图，不会再出现固定深色的「黑方块」。
        base_ph = glass_over_bg(w, h, rx, ry, win_w, win_h, 0, PANEL_LAYERS)
        if self._base_id is not None:
            self.delete(self._base_id)
        self._base_id = self.create_image(0, 0, anchor="nw", image=base_ph)
        self.tag_lower(self._base_id)
        self._base_ph = base_ph

        # 上层：圆角卡片。透明玻璃卡 = 背景图 + 卡片叠层（含真实背景、
        # 半透明）。keep_outside=False 让圆角外透明、露出底层 PANEL 玻璃；
        # 一圈克制的细亮边（与 outer 同强度），强化玻璃框轮廓；非玻璃卡用纯色。
        if self.glass and self.fill == CARD:
            photo = glass_over_bg(w, h, rx, ry, win_w, win_h, self.radius,
                                  CARD_LAYERS, edge=0.08, highlight=0.0,
                                  keep_outside=True,
                                  outside_layers=PANEL_LAYERS,
                                  edge_color="#8A8A96", blur=5.0)
            # 记住这块玻璃的实际色，tint() 要拿它刷内部控件，
            # 这样 Text/Label/Frame 就不会在透明卡片上留白板
            self._inner_bg = card_inner_color(
                w, h, rx, ry, win_w, win_h, CARD_LAYERS, blur=5.0)
        else:
            photo = round_image(w, h, self.radius, self.fill)
            self._inner_bg = self.fill
        if self._bg_id is not None:
            self.delete(self._bg_id)
        self._bg_id = self.create_image(0, 0, anchor="nw", image=photo)
        # 从底到顶：base 面板 < bg 卡片 < body 窗口。先压 bg 再压 base，
        # base 落最底，bg 恰在 base 之上，window 保持最上。
        self.tag_lower(self._bg_id)
        self.tag_lower(self._base_id)
        # body 铺满卡片内部（边缘过渡带本身就是材质色，盖住也无妨）
        bh = max(1, h - self.pad * 2 - self.bottom_band)
        self.itemconfig(self._win, width=max(1, w - self.pad * 2),
                        height=bh)
        # body 尺寸被强制后，让它按新尺寸重绘真实背景玻璃，避免露出 BG 黑条
        try:
            self.after_idle(self.body._paint)
        except Exception:
            pass
        self._photo = photo                     # 保住引用，别被 GC

    def refresh(self) -> None:
        """往 .body 里动态增删控件之后必须调一次。

        卡片里的 body 高度是画布窗口项**强制**的，新加的控件没有空间就
        不会 map（也不触发 body 的 <Configure>），表现为「加了控件但看不见」。
        这里先放开强制高度，让 body 按自己的需求尺寸重新算，再同步画布。
        """
        try:
            self.itemconfig(self._win, height=0)
            self.update_idletasks()
            need = self.body.winfo_reqheight() + self.pad * 2
            if abs(need - int(self["height"])) > 0:
                self.configure(height=need)
            self.update_idletasks()
            self._redraw()
            self.tint()
        except Exception:
            pass

    # ---------------- 内部材质统一：按位置匹配透明玻璃等效色 ----------------
    def tint(self, _e=None) -> None:
        """让卡片内所有不透明控件「伪装」成透明玻璃。

        body 是渲染真实背景玻璃的 GradientPane（背景图案可见），这里先让
        它按当前位置重绘，再遍历子树：普通 Frame/Label/画布/日志框按各自
        位置取等效固定色，于是文字清晰、缝隙与下方真实背景对齐。
        """
        if not self.glass:
            return
        try:
            self.body._paint()
            self._tint_walk(self.body, 0)
        except Exception:
            pass

    def _eq_for(self, c) -> str | None:
        """控件 c 当前位置对应的透明玻璃等效色。"""
        try:
            top = self.winfo_toplevel()
            win_w, win_h = top.winfo_width(), top.winfo_height()
            if win_w < 4 or win_h < 4:
                return None
            rx = c.winfo_rootx() - top.winfo_rootx()
            ry = c.winfo_rooty() - top.winfo_rooty()
            cw = c.winfo_width()
            ch = c.winfo_height()
            if cw <= 1:
                cw = c.winfo_reqwidth()
            if ch <= 1:
                ch = c.winfo_reqheight()
            return glass_equivalent_color(
                rx, ry, max(1, cw), max(1, ch), win_w, win_h, CARD_LAYERS)
        except Exception:
            return None

    def _tint_walk(self, w, depth: int = 0) -> None:
        if depth > 12:
            return
        # GradientPane（含 body）靠自身 _paint 渲染真实背景，不改 bg；
        # 其余普通容器/文字/画布/日志框匹配位置等效色；Entry 与 ttk 跳过。
        # 标记了 _keep_bg 的控件（如分区分隔线）保留固定底色，不被改色。
        if not isinstance(w, GradientPane) and not getattr(w, "_keep_bg", False):
            try:
                cls = w.winfo_class()
            except Exception:
                cls = ""
            if cls in ("Frame", "Label", "Labelframe", "Canvas", "Text"):
                color = self._eq_for(w)
                if color:
                    try:
                        changed = str(w["bg"]) != color
                        if changed:
                            w.configure(bg=color)
                        # 开关这类自带圆角图片的控件要跟着重画，
                        # 它圆角外的填充色必须等于当前底色（否则是黑角）
                        if changed and hasattr(w, "refresh"):
                            w.refresh(color)
                    except Exception:
                        pass
        for c in w.winfo_children():
            self._tint_walk(c, depth + 1)


class WinButton(tk.Canvas):
    """窗口控制按钮（最小化 / 最大化 / 关闭）。

    去标题栏后系统那三个按钮没了，自己画。默认是极淡的灰线，
    悬停才浮出来 —— 不抢视线，但指到就知道能点。
    """

    def __init__(self, master, kind: str, command=None, bg: str = HEAD_BG,
                 size: int = 30, **kw):
        super().__init__(master, width=size, height=size,
                         highlightthickness=0, bd=0, bg=bg,
                         cursor="hand2", **kw)
        self._kind = kind
        self._bg = bg
        self._size = size
        self._hover = False
        # 关闭键悬停用红色，和系统习惯一致
        self._hover_fill = "#E81123" if kind == "close" else CARD3
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._command = command

    def _on_enter(self, _e=None):
        self._hover = True
        self._draw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._draw()

    def _on_release(self, e):
        if 0 <= e.x <= self._size and 0 <= e.y <= self._size and self._command:
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        s = self._size
        if self._hover:
            fill = self._hover_fill
            photo = glass_image(s, s, 8,
                                top=_mix(fill, "#FFFFFF", 0.10),
                                bottom=_mix(fill, "#000000", 0.12),
                                edge=0.10, highlight=0.14,
                                outside_color=self._bg)
            self.create_image(0, 0, anchor="nw", image=photo)
            self._photo = photo
            fg = "#FFFFFF" if self._kind == "close" else TEXT
        else:
            fg = TEXT3

        cx = cy = s / 2
        w = 2 if self._kind == "close" else 1.6
        if self._kind == "close":
            # ×
            cv = 4.5
            self.create_line(cx - cv, cy - cv, cx + cv, cy + cv,
                             fill=fg, width=w, capstyle="round")
            self.create_line(cx - cv, cy + cv, cx + cv, cy - cv,
                             fill=fg, width=w, capstyle="round")
        elif self._kind == "max":
            # □
            r = 4.5
            self.create_rectangle(cx - r, cy - r, cx + r, cy + r,
                                  outline=fg, width=w)
        elif self._kind == "restore":
            # 两个叠起来的小方框（还原）
            r = 3.6
            self.create_rectangle(cx - r + 1.6, cy - r - 0.6,
                                  cx + r + 0.8, cy + r - 3.0,
                                  outline=fg, width=w)
            self.create_rectangle(cx - r - 0.8, cy - r + 2.2,
                                  cx + r - 1.6, cy + r + 0.4,
                                  outline=fg, width=w)
        else:
            # ─
            self.create_line(cx - 5, cy, cx + 5, cy,
                             fill=fg, width=w, capstyle="round")


class GlassTextLog(tk.Canvas):
    """真·透明日志：毛玻璃背景和文字画在**同一个 Canvas** 上。

    为什么不用 tk.Text：Text 的 bg 只能纯色，哪怕调成和玻璃一样的颜色，
    也只是一块均匀色板 —— 看不到背后的壁纸图案。Canvas 不一样：先把
    模糊玻璃图铺满（create_image），再把文字 create_text 上去，
    文字周围就是真实的玻璃，壁纸从下面透出来。

    接口尽量对齐 Text 的常用部分：append(text) / clear() / 自动滚到底。
    不支持编辑与选中（日志本来就是只读的）。
    """

    def __init__(self, master, radius: int = CARD_RADIUS,
                 layers: tuple[tuple[str, float], ...] = CARD_LAYERS,
                 blur: float = 5.0, font=None, fg: str = TEXT2,
                 padding: int = 10, line_gap: int = 2, **kw):
        super().__init__(master, highlightthickness=0, bd=0, bg=BG,
                         **kw)
        self._radius = radius
        self._layers = layers
        self._blur = blur
        self._font = font or (FONT, FS_SMALL)
        self._fg = fg
        self._pad = padding
        self._gap = line_gap
        self._next_y = padding
        self._bg_id = None
        self._ph = None
        self._lines = []
        self.bind("<Configure>", self._paint)

    # ---------------- 背景
    def _paint(self, _e=None) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        try:
            top = self.winfo_toplevel()
            win_w, win_h = top.winfo_width(), top.winfo_height()
            rx = self.winfo_rootx() - top.winfo_rootx()
            ry = self.winfo_rooty() - top.winfo_rooty()
            ph = glass_over_bg(w, h, rx, ry, win_w, win_h, self._radius,
                               self._layers, keep_outside=False,
                               blur=self._blur)
        except Exception:
            return
        self._ph = ph
        if self._bg_id is not None:
            self.delete(self._bg_id)
        self._bg_id = self.create_image(0, 0, anchor="nw", image=ph)
        self.tag_lower(self._bg_id)
        # 重排文字（宽度变了要重新换行）
        self._relayout()

    def _text_width(self) -> int:
        return max(40, self.winfo_width() - self._pad * 2)

    def _relayout(self) -> None:
        if not self._lines:
            self._next_y = self._pad
            return
        self.delete("txt")
        y = self._pad
        for line in self._lines:
            item = self.create_text(self._pad, y, anchor="nw", text=line,
                                    width=self._text_width(), fill=self._fg,
                                    font=self._font, tags="txt")
            bb = self.bbox(item)
            y = (bb[3] if bb else y + 16) + self._gap
        self._next_y = y
        self.configure(scrollregion=(0, 0, self.winfo_width(), y + self._pad))
        self.yview_moveto(1.0)

    # ---------------- 接口（对齐 tk.Text 的常用用法）
    def append(self, line: str) -> None:
        self._lines.append(line)
        if len(self._lines) > 2000:            # 别无限涨
            self._lines = self._lines[-1500:]
            self._relayout()
            return
        item = self.create_text(self._pad, self._next_y, anchor="nw",
                                text=line, width=self._text_width(),
                                fill=self._fg, font=self._font, tags="txt")
        bb = self.bbox(item)
        self._next_y = (bb[3] if bb else self._next_y + 16) + self._gap
        self.configure(
            scrollregion=(0, 0, self.winfo_width(), self._next_y + self._pad))
        self.yview_moveto(1.0)

    def clear(self) -> None:
        self._lines.clear()
        self.delete("txt")
        self._next_y = self._pad
        self.configure(scrollregion=(0, 0, self.winfo_width(), self._pad))

    def set_fg(self, color: str) -> None:
        self._fg = color
        try:
            self.itemconfigure("txt", fill=color)
        except Exception:
            pass

    # 让外部按 Text 的习惯写法也能跑
    def insert(self, _index, text: str) -> None:
        self.append(text.rstrip("\n"))

    def see(self, _index) -> None:
        self.yview_moveto(1.0)

    def configure_state(self, _state: str) -> None:
        pass

    def yview(self, *args):
        return super().yview(*args)


class RoundButton(tk.Canvas):
    """圆角按钮，带 hover / 按下反馈。"""

    def __init__(self, master, text: str, command=None, width: int = 96,
                 height: int = 32, radius: int = BTN_RADIUS,
                 fill: str = CARD2, fg: str = TEXT, hover: str = CARD3,
                 font_size: int = FS, bold: bool = False, bg: str = CARD, **kw):
        # bg 必须是「父容器」的颜色：画布底色和圆角外露出的就是这个色，
        # 写死成窗口背景会在卡片里挖出四个暗角
        super().__init__(master, width=width, height=height,
                         highlightthickness=0, bd=0, bg=bg, **kw)
        self._text = text
        self._command = command
        self._fill = fill
        self._hover = hover
        self._fg = fg
        self._radius = radius
        self._font = (FONT, font_size, "bold") if bold else (FONT, font_size)
        self._enabled = True
        self._draw(fill)
        self.bind("<Enter>", lambda _e: self._draw(self._hover))
        self.bind("<Leave>", lambda _e: self._draw(self._fill))
        self.bind("<ButtonPress-1>", lambda _e: self._draw(self._hover))
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, color: str) -> None:
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        # 玻璃感：同色系上亮下暗 + 一圈极细亮边
        top = _mix(color, "#FFFFFF", 0.16)
        bot = _mix(color, "#000000", 0.14)
        photo = glass_image(w, h, self._radius,
                            top="#%02X%02X%02X" % top,
                            bottom="#%02X%02X%02X" % bot,
                            edge=0.14, highlight=0.20,
                            outside_color=self.cget("bg"))
        self.create_image(0, 0, anchor="nw", image=photo)
        self._photo = photo
        fg = self._fg if self._enabled else TEXT3
        self.create_text(w // 2, h // 2, text=self._text,
                         fill=fg, font=self._font)

    def _on_release(self, event) -> None:
        self._draw(self._hover)
        inside = 0 <= event.x <= int(self["width"]) and 0 <= event.y <= int(self["height"])
        if inside and self._enabled and self._command:
            self._command()

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw(self._fill)

    def set_enabled(self, ok: bool) -> None:
        self._enabled = bool(ok)
        self._draw(self._fill)

    def set_command(self, command) -> None:
        """换绑点击回调（任务完成后把「更新」换成「重启」这类）。"""
        self._command = command

    def set_fill(self, fill: str) -> None:
        """换底色（开关类按钮用：开启绿、关闭灰）。"""
        self._fill = fill
        self._draw(fill)


class RoundProgress(tk.Canvas):
    """圆角进度条。ttk.Progressbar 在 clam 主题下样式不跟配色走，自己画。"""

    def __init__(self, master, width: int = 420, height: int = 8,
                 fill: str = BLUE, track: str = CARD2, bg: str = PANEL, **kw):
        super().__init__(master, width=width, height=height,
                         highlightthickness=0, bd=0, bg=bg, **kw)
        # 别用 self._w / self._h —— self._w 是 tkinter 内部的控件路径名，覆盖了会炸
        self._bar_w, self._bar_h = width, height
        self._fill, self._track = fill, track
        self._value = 0.0
        self._track_id = self.create_rectangle(
            0, 0, width, height, fill=track, outline="")
        self._bar_id = self.create_rectangle(
            0, 0, 0, height, fill=fill, outline="")

    def set_value(self, pct: float) -> None:
        self._value = max(0.0, min(100.0, float(pct)))
        w = self._bar_w * self._value / 100.0
        self.coords(self._bar_id, 0, 0, w, self._bar_h)

    def get_value(self) -> float:
        return self._value


class RoundEntry(tk.Frame):
    """圆角输入框：圆角背景 + 无边框 Entry。

    placeholder：水印提示，聚焦时消失、失焦且空时复原。
    """

    def __init__(self, master, width: int = 200, height: int = 30,
                 radius: int = BTN_RADIUS, fill: str = CARD2,
                 show: str = "", bg: str = CARD,
                 placeholder: str = "", **kw):
        super().__init__(master, bg=bg, **kw)
        self._ph = placeholder
        self._show = show
        self._showing_ph = False
        self.canvas = tk.Canvas(self, width=width, height=height,
                                highlightthickness=0, bd=0, bg=bg)
        self.canvas.pack()
        photo = glass_image(width, height, radius,
                            top="#%02X%02X%02X" % _mix(fill, "#FFFFFF", 0.09),
                            bottom="#%02X%02X%02X" % _mix(fill, "#000000", 0.10),
                            edge=0.09, highlight=0.10,
                            outside_color=bg)
        self.canvas.create_image(0, 0, anchor="nw", image=photo)
        self._photo = photo
        self.entry = tk.Entry(self.canvas, bd=0, relief="flat", bg=fill,
                              fg=TEXT, insertbackground=TEXT,
                              font=(FONT, FS), show=show)
        self.canvas.create_window(10, height // 2, anchor="w", window=self.entry,
                                  width=max(20, width - 20), height=height - 8)
        if self._ph:
            self.entry.bind("<FocusIn>", self._on_focus_in)
            self.entry.bind("<FocusOut>", self._on_focus_out)
            self._apply_ph()

    # -------- 水印 --------
    def _apply_ph(self) -> None:
        self.entry.configure(fg=TEXT3, show="")            # 水印时不能遮码
        self.entry.delete(0, "end")
        self.entry.insert(0, self._ph)
        self._showing_ph = True

    def _clear_ph(self) -> None:
        self.entry.delete(0, "end")
        self.entry.configure(fg=TEXT, show=self._show)
        self._showing_ph = False

    def _on_focus_in(self, _event=None) -> None:
        if self._showing_ph:
            self._clear_ph()

    def _on_focus_out(self, _event=None) -> None:
        if not self._showing_ph and not self.entry.get().strip():
            self._apply_ph()

    # -------- 对外 API（保持与旧版一致）--------
    def get(self) -> str:
        return "" if self._showing_ph else self.entry.get()

    def set(self, text: str) -> None:
        if self._showing_ph:
            self._clear_ph()
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        if not text and self._ph:
            self._apply_ph()


class RoundCombo(tk.Canvas):
    """自绘圆角玻璃下拉框。

    为什么不用 ttk.Combobox：它有两处没法看 ——
    · 主控件顶部那条白带：glass_image 的 highlight 在 30px 高的控件上
      就是 3px 宽的白高光，浅色背景上像贴了张白条
    · 点开的列表是原生 Listbox：直角、纯白底、选中色是系统蓝，
      和周围的圆角玻璃完全不搭

    所以整块自己画：
    · 主控件 —— 圆角玻璃（不带高光）+ 左对齐文字 + 自绘小箭头
    · 弹出层 —— 独立 Toplevel，圆角 + 暗边，每项 create_text 排，
      鼠标经过画圆角浅蓝高亮，当前值前面打勾
    · 项多时滚轮可滚

    对外接口和原来一致：get / set / set_values / bind_select / var / [values]
    """

    ROW_H = 28          # 每项高度（实际按文本量算，这是下限）
    PAD = 8             # 弹出层上下留白

    def __init__(self, master, values: list[str], width: int = 200,
                 height: int = 30, radius: int = BTN_RADIUS,
                 fill: str = CARD2, readonly: bool = True,
                 bg: str = CARD, **kw):
        super().__init__(master, width=width, height=height,
                         highlightthickness=0, bd=0, bg=bg,
                         cursor="hand2", **kw)
        # 注意：不能叫 _w / _h —— 那是 tkinter Widget 内部属性
        self._cw, self._ch = int(width), int(height)
        self._radius = radius
        self._fill = fill
        self._bg = bg
        self._readonly = readonly
        self._ph = None
        self._values = [str(v) for v in values]
        self.var = tk.StringVar(value=self._values[0] if self._values else "")
        self._on_select = None
        self._pop = None
        self._pop_cv = None
        self._pop_photo = None
        self._scroll = 0
        self._row_h = []
        self._geom = []
        self._pop_w = int(width)
        self._pop_h = 0
        self._draw()
        self.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *_a: self._draw())

    # ---------------------------------------------------------------- 主控件
    def _fit_text(self, text: str, max_w: int) -> str:
        """太长就截断加省略号，保证永远单行。"""
        text = str(text or "")
        if not text or max_w <= 8:
            return text
        try:
            if not hasattr(self, "_fnt"):
                self._fnt = tkfont.Font(font=(FONT, FS))
            f = self._fnt
            if f.measure(text) <= max_w:
                return text
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if f.measure(text[:mid] + "…") <= max_w:
                    lo = mid
                else:
                    hi = mid - 1
            return (text[:lo] + "…") if lo > 0 else "…"
        except Exception:
            return text

    def _draw(self) -> None:
        self.delete("all")
        # highlight=0：这块不画顶部高光，否则就是那条白带。
        # 用极轻的上下渐变 + 暗细边表达「凹进去的输入框」。
        photo = glass_image(self._cw, self._ch, self._radius,
                            top=self._fill,
                            bottom="#%02X%02X%02X" % _mix(
                                self._fill, "#000000", 0.07),
                            edge=0.18, highlight=0.0, inner_shadow=0.14,
                            outside_color=self._bg)
        self._ph = photo
        self.create_image(0, 0, anchor="nw", image=photo)

        arrow_w = 20
        pad = 11
        # 单行 + 超长省略：「变声器输出 (VB-Audio Virtual Cable)」这种
        # 折成两行会溢出 30px 高的控件，下拉框本来就该是一行
        avail = max(24, self._cw - pad - arrow_w - 4)
        text = self._fit_text(self.var.get(), avail)
        self.create_text(pad, self._ch // 2, anchor="w", text=text,
                         fill=TEXT, font=(FONT, FS))
        # 小箭头：两条线折成 V，比默认三角轻
        cx, cy = self._cw - 13, self._ch / 2 - 1
        self.create_line(cx - 4, cy - 2, cx, cy + 2.5, cx + 4, cy - 2,
                         fill=TEXT2, width=1.6, capstyle="round",
                         joinstyle="round")

    # ---------------------------------------------------------------- 弹出层
    def _toggle(self, _e=None) -> None:
        if self._pop is not None:
            self._close()
        else:
            self._open()

    def _measure_rows(self, text_w: int) -> list[int]:
        """量每一项排完要占多高。

        必须量：像「变声器输出 (VB-Audio Virtual Cable)」这种长名字在
        窄下拉里会折成两行，行高固定 28 就会互相压字（实测就是这样）。
        """
        meas = tk.Canvas(self)
        out = []
        try:
            for v in self._values:
                it = meas.create_text(0, 0, anchor="nw", text=v,
                                      font=(FONT, FS), width=text_w)
                bb = meas.bbox(it)
                h = (bb[3] - bb[1]) if bb else 18
                out.append(max(26, h + 10))
        except Exception:
            out = [28] * len(self._values)
        finally:
            try:
                meas.destroy()
            except Exception:
                pass
        return out

    def _open(self) -> None:
        if not self._values or self._pop is not None:
            return
        w = max(self._cw, 140)
        text_w = max(60, w - self.PAD * 2 - 26)
        self._row_h = self._measure_rows(text_w)
        total = sum(self._row_h) + self.PAD * 2
        h = min(total, 340)
        self._pop_h = h
        self._pop_w = w

        x = self.winfo_rootx()
        y = self.winfo_rooty() + self._ch + 4
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:
            sw = sh = 0
        if sh and y + h > sh - 10:
            y = max(8, self.winfo_rooty() - h - 4)
        if sw and x + w > sw - 10:
            x = max(8, sw - w - 10)

        top = tk.Toplevel(self)
        try:
            top.overrideredirect(True)
        except Exception:
            pass
        try:
            top.attributes("-topmost", True)
        except Exception:
            pass

        # 不用 -transparentcolor：圆角是抗锯齿画的，边缘像素会和透明色
        # 混成一道粉边（实测四个角都有）。这里直接把圆角外画成面板色，
        # 浅色界面下面板和它所在卡片同色，四角看不出差异
        try:
            top.configure(bg=CARD)
            top.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        cv = tk.Canvas(top, width=w, height=h, highlightthickness=0, bd=0,
                       bg=CARD, cursor="hand2")
        cv.pack(fill="both", expand=True)

        photo = round_image(w, h, 13, CARD, outline="#9AA0AE",
                            outside=CARD)
        cv.create_image(0, 0, anchor="nw", image=photo)
        cv._bg_photo = photo          # 防 GC

        self._pop = top
        self._pop_cv = cv
        self._hl = cv.create_rectangle(0, 0, 0, 0, fill="#DCE9FF",
                                       outline="", state="hidden")
        self._geom = []
        self._layout()

        cv.bind("<Motion>", self._on_motion)
        cv.bind("<Button-1>", self._on_click)
        cv.bind("<ButtonRelease-1>", self._on_click)
        cv.bind("<MouseWheel>", self._on_wheel)
        cv.bind("<Leave>", lambda _e: cv.itemconfigure(self._hl,
                                                       state="hidden"))
        top.bind("<Escape>", lambda _e: self._close())
        try:
            self.winfo_toplevel().bind_all("<Button-1>", self._maybe_close,
                                           add="+")
        except Exception:
            pass
        try:
            top.focus_force()
        except Exception:
            pass

    def _layout(self) -> None:
        """从 self._scroll 开始往下排，装不下就停（剩下的靠滚轮）。"""
        cv = self._pop_cv
        if cv is None:
            return
        cv.delete("row")
        self._geom = []
        cur = self.var.get()
        avail = self._pop_h - self.PAD * 2
        y = float(self.PAD)
        used = 0.0
        text_w = max(60, self._pop_w - self.PAD * 2 - 26)
        for i in range(self._scroll, len(self._values)):
            rh = self._row_h[i] if i < len(self._row_h) else 28
            if used + rh > avail + 0.5:
                break
            v = self._values[i]
            cv.create_text(self.PAD + 22, y + rh / 2, anchor="w", text=v,
                           fill=TEXT, font=(FONT, FS), width=text_w,
                           tags=("row",))
            if v == cur:
                mid = y + rh / 2
                cv.create_line(self.PAD + 6, mid,
                               self.PAD + 9, mid + 3.2,
                               self.PAD + 13, mid - 3.2,
                               fill=BLUE, width=1.8, capstyle="round",
                               joinstyle="round", tags=("row",))
            self._geom.append((y, y + rh, i))
            y += rh
            used += rh

    def _visible(self) -> int:
        return len(self._geom) or 1

    def _index_at(self, y) -> int:
        for y0, y1, i in self._geom:
            if y0 <= y < y1:
                return i
        return -1

    def _on_motion(self, e) -> None:
        if self._pop_cv is None:
            return
        for y0, y1, _i in self._geom:
            if y0 <= e.y < y1:
                w = self._pop_w
                self._pop_cv.coords(self._hl, self.PAD + 4, y0 + 1,
                                    w - self.PAD - 4, y1 - 1)
                self._pop_cv.itemconfigure(self._hl, state="normal")
                self._pop_cv.tag_lower(self._hl, "row")
                return
        self._pop_cv.itemconfigure(self._hl, state="hidden")

    def _on_click(self, e) -> None:
        i = self._index_at(e.y)
        if i >= 0:
            self._pick(self._values[i])

    def _on_wheel(self, e) -> None:
        if self._pop is None:
            return
        if sum(self._row_h) + self.PAD * 2 <= self._pop_h + 1:
            return                      # 全都塞得下，不用滚
        step = -1 if e.delta > 0 else 1
        self._scroll = max(0, min(len(self._values) - 1,
                                  self._scroll + step))
        self._layout()
        if self._pop_cv is not None:
            self._pop_cv.itemconfigure(self._hl, state="hidden")

    def _maybe_close(self, _e=None) -> None:
        """点了主窗口其他地方就收起列表。"""
        if self._pop is None:
            return
        try:
            px, py = self._pop.winfo_rootx(), self._pop.winfo_rooty()
            pw, ph = self._pop.winfo_width(), self._pop.winfo_height()
            wx = self.winfo_pointerx()
            wy = self.winfo_pointery()
            inside = (px <= wx <= px + pw) and (py <= wy <= py + ph)
            mine = (self.winfo_rootx() <= wx <= self.winfo_rootx() + self._cw
                    and self.winfo_rooty() <= wy
                    <= self.winfo_rooty() + self._ch)
            if not inside and not mine:
                self._close()
        except Exception:
            pass

    def _pick(self, value: str) -> None:
        self.var.set(value)
        self._close()
        if self._on_select:
            self._on_select()

    def _close(self) -> None:
        pop = self._pop
        self._pop = None
        self._pop_cv = None
        self._scroll = 0
        self._geom = []
        try:
            self.winfo_toplevel().unbind_all("<Button-1>")
        except Exception:
            pass
        if pop is not None:
            try:
                pop.destroy()
            except Exception:
                pass

    # ---------------------------------------------------------------- 接口
    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def set_values(self, values: list[str]) -> None:
        self._values = [str(v) for v in values]
        if self._pop is not None:
            self._close()
        self._draw()

    def bind_select(self, func) -> None:
        self._on_select = func

    def destroy(self):
        self._close()
        super().destroy()

    # 兼容字典式访问（cb["values"] = [...]）
    def __setitem__(self, key, value):
        if key == "values":
            self.set_values(list(value))
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        if key == "values":
            return self._values
        return super().__getitem__(key)


class ToggleRow(tk.Frame):
    """iOS 风格开关行：左边文字，右边胶囊开关。

    extra 是文字和开关之间的空位，调用方可以往里塞附加控件
    （比如手机遥控的地址 + 二维码按钮），保持一行。
    """

    def __init__(self, master, text: str, variable: tk.BooleanVar,
                 command=None, bg: str = CARD, **kw):
        super().__init__(master, bg=bg, **kw)
        self.var = variable
        self.command = command
        self._bg = bg
        # 注意：不能叫 _w / _h，那是 tkinter Widget 内部的 widget path
        self._sw, self._sh = 42, 24
        self._label = tk.Label(self, text=text, bg=bg, fg=TEXT,
                               font=(FONT, FS), anchor="w")
        self._label.pack(side="left")
        self.switch = tk.Canvas(self, width=self._sw, height=self._sh,
                                highlightthickness=0, bd=0, bg=bg,
                                cursor="hand2")
        self.switch.pack(side="right", padx=(10, 0))
        # 中间扩展区（默认不占位，有子控件才显形）
        self.extra = tk.Frame(self, bg=bg)
        self._draw()
        self.switch.bind("<Button-1>", self._toggle)
        self._label.bind("<Button-1>", self._toggle)

    def pack_extra(self) -> None:
        """把 extra 插到文字和开关之间。有内容时调一次即可。"""
        if not self.extra.winfo_manager():
            self.extra.pack(side="left", fill="x", expand=True,
                            padx=(10, 0))

    def _draw(self) -> None:
        c = self.switch
        c.delete("all")
        on = bool(self.var.get())
        color = GREEN if on else CARD3
        # 圆角外填当前底色，否则 Tk 会把透明像素画成黑角
        bg = self.cget("bg")
        photo = round_image(self._sw, self._sh, self._sh // 2, color,
                            outside=bg)
        c.create_image(0, 0, anchor="nw", image=photo)
        self._photo = photo
        r = self._sh // 2 - 2
        cx = self._sw - r - 2 if on else r + 2
        knob = round_image(r * 2, r * 2, r, "#FFFFFF", outside=bg)
        c.create_image(cx - r, self._sh // 2 - r, anchor="nw", image=knob)
        self._knob = knob

    def refresh(self, bg: str | None = None) -> None:
        """被卡片 tint() 改色后重画开关（黑角靠它跟着底色一起变）。"""
        if bg:
            self._bg = bg
            try:
                self.configure(bg=bg)
                self._label.configure(bg=bg)
                self.extra.configure(bg=bg)
                self.switch.configure(bg=bg)
            except Exception:
                pass
        self._draw()

    def _toggle(self, _event=None) -> None:
        self.var.set(not self.var.get())
        self._draw()
        if self.command:
            self.command()


def make_styles() -> None:
    """全局 ttk 样式：滚动条、日志框等。"""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    # 玻璃风细滚动条：trough 与玻璃同色（隐形），thumb 是浅色滑块，
    # 不用黑色 trough，避免在浅色玻璃上出现一条近黑竖线。
    style.configure("Vertical.TScrollbar", background=CARD3, troughcolor=PANEL,
                    bordercolor=PANEL, lightcolor=CARD3, darkcolor=CARD3,
                    arrowcolor=PANEL, relief="flat", width=6, borderwidth=0,
                    arrowsize=0)
    style.map("Vertical.TScrollbar",
              background=[("active", "#5A5A72"), ("pressed", "#6A6A84")])
    # 去掉上下箭头，只留一根细滑块 —— 默认那两个小三角在深色界面上很扎眼
    try:
        style.layout("Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {
                "sticky": "nsew",
                "children": [
                    ("Vertical.Scrollbar.thumb",
                     {"expand": "1", "sticky": "nswe"}),
                ],
            }),
        ])
    except Exception:
        pass


class ThinScrollbar(tk.Canvas):
    """自研玻璃风细滚动条，替代 ttk.Scrollbar。

    ttk 滚动条在 clam 下用自定义 layout 时物理宽度会塌陷成 1px、且 trough
    是近黑色，在浅色玻璃上就是一条黑线。这里用普通 Canvas：宽度固定、
    trough 与玻璃同色（PANEL）、圆角浅色 thumb，完全可控。

    接口与 ttk 滚动条对齐：
    - set(first, last)：作为 yscrollcommand 回调，更新 thumb 位置与大小
    - command（目标 Canvas 的 yview）：拖动时调用 yview("moveto", frac)
    """

    WIDTH = 8
    MIN_THUMB = 26
    TROUGH = "#DCDCE2"          # 和背景同色，视觉隐形，只剩滑块
    THUMB = "#B4B4BE"           # 浅灰滑块，悬停加深

    def __init__(self, master, command=None, **kw):
        super().__init__(master, width=self.WIDTH, highlightthickness=0,
                         bd=0, bg=self.TROUGH, cursor="arrow", **kw)
        self._target = command
        self._f = 0.0
        self._l = 1.0
        self._drag_offset = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)

    def set_command(self, cmd) -> None:
        self._target = cmd

    def set(self, first, last) -> None:
        try:
            self._f = max(0.0, min(1.0, float(first)))
            self._l = max(0.0, min(1.0, float(last)))
        except Exception:
            return
        self._draw()

    def _thumb_geom(self):
        h = max(1, self.winfo_height())
        th = max(self.MIN_THUMB, (self._l - self._f) * h)
        y0 = self._f * (h - th) if self._l - self._f < 0.999 else 0
        return y0, th

    def _draw(self) -> None:
        self.delete("thumb")
        h = self.winfo_height()
        if h < 8 or self._l - self._f >= 0.999:
            return
        y0, th = self._thumb_geom()
        x0, x1 = 2, self.WIDTH - 2
        r = (x1 - x0) / 2
        pts = [
            x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
            x1, y0 + th - r, x1, y0 + th, x1 - r, y0 + th,
            x0 + r, y0 + th, x0, y0 + th, x0, y0 + th - r,
            x0, y0 + r, x0, y0,
        ]
        self.create_polygon(pts, smooth=True, fill=self.THUMB, outline="",
                            tags="thumb")

    def _moveto(self, frac) -> None:
        frac = max(0.0, min(1.0, float(frac)))
        if self._target:
            try:
                self._target("moveto", frac)
            except Exception:
                pass

    def _press(self, e) -> None:
        y0, th = self._thumb_geom()
        if y0 <= e.y <= y0 + th:
            self._drag_offset = e.y - y0
        else:
            frac = (e.y - th / 2) / max(1, self.winfo_height() - th)
            self._moveto(frac)
            self._drag_offset = th / 2

    def _drag(self, e) -> None:
        if self._drag_offset is None:
            return
        th = self._thumb_geom()[1]
        frac = (e.y - self._drag_offset) / max(1, self.winfo_height() - th)
        self._moveto(frac)

    def _release(self, _e=None) -> None:
        self._drag_offset = None