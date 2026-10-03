#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 icon.ico —— 圆形方孔钱（铜钱）。

为什么自己画：桌面快捷方式用系统图标库里的齿轮/工具图标，一眼看不出是干什么的；
画成铜钱就跟这个工具（改钱、改资源）对上了。

几何全部按比例算，从 256 缩到 16 也不会糊成一团。不依赖任何字体。

用法（用自带 Pillow 的 Python）：
    python make_icon.py
生成：icon.ico
"""

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("[出错] 需要 Pillow：pip install Pillow")
    sys.exit(1)

HERE = Path(__file__).resolve().parent
ICO = HERE / "icon.ico"

# 配色：深色底 + 金色钱
DARK = (34, 30, 24, 255)        # 底板
GOLD = (226, 180, 66, 255)      # 钱体
EDGE = (138, 102, 22, 255)      # 描边
HOLE = (34, 30, 24, 255)        # 方孔（跟底板同色，看起来是"空"的）

SIZES = [256, 128, 64, 48, 32, 24, 16]


def draw_coin(size: int) -> Image.Image:
    """按给定边长画一枚铜钱，所有尺寸都从比例算出来。"""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底板
    pad = max(1, round(s * 0.030))
    radius = max(2, round(s * 0.200))
    plate_lw = max(1, round(s * 0.026))
    d.rounded_rectangle([pad, pad, s - 1 - pad, s - 1 - pad], radius=radius,
                        fill=DARK, outline=EDGE, width=plate_lw)

    c = s / 2.0

    # 钱体（外圆）
    r = s * 0.348
    coin_lw = max(1, round(s * 0.022))
    d.ellipse([c - r, c - r, c + r, c + r],
              fill=GOLD, outline=EDGE, width=coin_lw)

    # 方孔
    h = s * 0.128
    d.rectangle([c - h, c - h, c + h, c + h],
                fill=HOLE, outline=EDGE, width=coin_lw)

    return img


def main():
    # 大图用来生成 ico，各尺寸由 Pillow 高质量缩放
    base = draw_coin(256)
    base.save(ICO, format="ICO",
              sizes=[(n, n) for n in SIZES])

    # 顺便存一张 PNG 方便预览
    png = HERE / "icon_preview.png"
    base.resize((256, 256), Image.Resampling.LANCZOS).save(png, format="PNG")

    print(f"[完成] {ICO}  （{ICO.stat().st_size:,} 字节，含 "
          f"{'/'.join(str(n) for n in SIZES)} 各尺寸）")
    print(f"[完成] {png}  （预览用）")


if __name__ == "__main__":
    main()
