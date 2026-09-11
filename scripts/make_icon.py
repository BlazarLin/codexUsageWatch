# -*- coding: utf-8 -*-
# 创建时间: 2026-09-11
# 功能: 生成应用图标 assets/icon.ico 与 assets/icon_256.png
# 目的: 与悬浮窗 UI 同风格的矢量绘制图标(深色圆角卡片+品牌绿环形仪表),
#       超采样抗锯齿后降采样输出多尺寸 ico, 供 PyInstaller/NSIS/GitHub 使用。
# 用法: python scripts/make_icon.py  (仓库根目录执行)

import math
import os

from PIL import Image, ImageDraw

BASE = 256   # 输出基准尺寸
SS = 4       # 超采样倍数
W = BASE * SS

# 品牌色(与 main.py 一致)
GREEN = (52, 211, 153)
TRACK = (52, 56, 69)

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
assets = os.path.normpath(os.path.join(root, "assets"))
os.makedirs(assets, exist_ok=True)

# 1. 背景纵向渐变
img = Image.new("RGBA", (W, W))
d = ImageDraw.Draw(img)
top, bottom = (38, 41, 50), (22, 24, 29)
for y in range(W):
    t = y / (W - 1)
    color = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom))
    d.line([(0, y), (W, y)], fill=color + (255,))

# 2. 圆角遮罩(卡片外形)
mask = Image.new("L", (W, W), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=54 * SS, fill=255)
img.putalpha(mask)
d = ImageDraw.Draw(img)

# 3. 高光描边(上亮下暗, 单色低透明度近似)
d.rounded_rectangle([1, 1, W - 2, W - 2], radius=54 * SS - SS,
                    outline=(255, 255, 255, 40), width=SS)

# 4. 环形仪表: 全周轨道
cx = cy = W // 2
r = 74 * SS
ring_w = 20 * SS
bbox = [cx - r, cy - r, cx + r, cy + r]
d.arc(bbox, 0, 360, fill=TRACK + (255,), width=ring_w)

# 5. 剩余弧线(250°, 自顶点顺时针) + 圆头端点
start_deg, sweep = 270, 250
end_deg = start_deg + sweep
d.arc(bbox, start_deg, end_deg, fill=GREEN + (255,), width=ring_w)


def cap_point(deg):
    """PIL 角度约定: 0°=3点钟方向, 顺时针(y 轴向下)"""
    rad = math.radians(deg)
    return (cx + r * math.cos(rad), cy + r * math.sin(rad))


cap_r = ring_w / 2
for deg in (start_deg, end_deg):
    x, y = cap_point(deg)
    d.ellipse([x - cap_r, y - cap_r, x + cap_r, y + cap_r], fill=GREEN + (255,))

# 6. 降采样输出多尺寸 ico + 单张 256 png
img_small = img.resize((BASE, BASE), Image.LANCZOS)
ico_path = os.path.join(assets, "icon.ico")
img_small.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                (64, 64), (128, 128), (256, 256)])
img_small.save(os.path.join(assets, "icon_256.png"))
print("已生成:", ico_path)
