"""
生成初音未来 Q 版像素画 → C 头文件 (RGB565)
画布 56x80, 用于 TTGO T-Display 135x240
"""
import math

W, H = 56, 80

# RGB565 编码
def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

# 调色板
T = 0x0000       # 透明 (用深背景色替代)
BG = rgb565(8, 14, 23)       # 背景深蓝
SK = rgb565(255, 220, 200)   # 肤色
HA = rgb565(57, 197, 187)    # 初音绿发色
HA2= rgb565(30, 150, 140)    # 深发色
EY = rgb565(50, 180, 170)    # 眼睛
WH = rgb565(255, 255, 255)   # 白
BK = rgb565(20, 20, 30)      # 黑
BL = rgb565(255, 180, 180)   # 腮红
RD = rgb565(200, 50, 50)     # 红
HP = rgb565(180, 180, 190)   # 耳机灰
TP = rgb565(50, 60, 80)      # 上衣深灰蓝
SKT= rgb565(60, 70, 90)      # 裙子
SH = rgb565(70, 60, 50)      # 靴子
TIE= rgb565(57, 197, 187)    # 领带=发色

# 初始化全透明画布
canvas = [[BG for _ in range(W)] for _ in range(H)]

def rect(x, y, w, h, c):
    for dy in range(h):
        for dx in range(w):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H:
                canvas[ny][nx] = c

def circ(cx, cy, r, c, fill=True):
    for dy in range(-r, r+1):
        for dx in range(-r, r+1):
            if dx*dx + dy*dy <= r*r + 1:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < W and 0 <= ny < H:
                    if fill or (dx*dx + dy*dy >= (r-1)*(r-1)):
                        canvas[ny][nx] = c

def tri(x1,y1,x2,y2,x3,y3,c):
    """填充三角形 (bounding box 扫描)"""
    minx, maxx = max(0, min(x1,x2,x3)), min(W-1, max(x1,x2,x3))
    miny, maxy = max(0, min(y1,y2,y3)), min(H-1, max(y1,y2,y3))
    for y in range(miny, maxy+1):
        for x in range(minx, maxx+1):
            d1 = (x-x2)*(y1-y2) - (x1-x2)*(y-y2)
            d2 = (x-x3)*(y2-y3) - (x2-x3)*(y-y3)
            d3 = (x-x1)*(y3-y1) - (x3-x1)*(y-y1)
            neg = (d1<0) or (d2<0) or (d3<0)
            pos = (d1>0) or (d2>0) or (d3>0)
            if not (neg and pos):
                canvas[y][x] = c

def line(x1,y1,x2,y2,c,w=1):
    dx, dy = abs(x2-x1), abs(y2-y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    cx, cy = x1, y1
    while True:
        for wx in range(-w//2, (w+1)//2):
            for wy in range(-w//2, (w+1)//2):
                nx, ny = cx+wx, cy+wy
                if 0 <= nx < W and 0 <= ny < H:
                    canvas[ny][nx] = c
        if cx == x2 and cy == y2: break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy

cx, cy = W//2, 22  # 脸部中心

# ===== 双马尾 (最底层，画最长) =====
# 左马尾 - 从头部延伸到画面底部
tri(cx-10, cy-6,  cx-28, cy+18,  cx-24, cy+62, HA)
tri(cx-8, cy-4,   cx-24, cy+18,  cx-20, cy+62, HA)
rect(cx-26, cy+58, 6, 20, HA)
rect(cx-24, cy+74, 4, 6, HA2)
# 右马尾
tri(cx+10, cy-6,  cx+28, cy+18,  cx+24, cy+62, HA)
tri(cx+8, cy-4,   cx+24, cy+18,  cx+20, cy+62, HA)
rect(cx+20, cy+58, 6, 20, HA)
rect(cx+20, cy+74, 4, 6, HA2)

# 马尾高光
line(cx-22, cy+70, cx-22, cy+30, rgb565(120,230,220), 1)
line(cx+22, cy+70, cx+22, cy+30, rgb565(120,230,220), 1)

# ===== 刘海 (遮住额头) =====
rect(cx-13, cy-16, 26, 8, HA)  # 主刘海
rect(cx-16, cy-12, 6, 6, HA)   # 左侧发
rect(cx+10, cy-12, 6, 6, HA)   # 右侧发
# M字刘海尖
rect(cx-6, cy-20, 3, 8, HA)
rect(cx+3, cy-20, 3, 8, HA)
# 侧发
rect(cx-18, cy-8, 4, 12, HA)
rect(cx+14, cy-8, 4, 12, HA)

# ===== 耳机 =====
rect(cx-18, cy-10, 36, 3, HP)  # 头梁
rect(cx-19, cy-12, 5, 8, HP)   # 左耳罩
rect(cx+14, cy-12, 5, 8, HP)   # 右耳罩
rect(cx-17, cy-11, 3, 6, rgb565(220,220,230))  # 耳罩高光
rect(cx+16, cy-11, 3, 6, rgb565(220,220,230))

# ===== 脸 =====
circ(cx, cy, 12, SK)
circ(cx, cy, 12, rgb565(200,180,160), False)  # 轮廓

# ===== 眼睛 =====
eyeY = cy - 1
# 大眼睛 (初音标志性)
circ(cx-7, eyeY, 4, EY)
circ(cx+7, eyeY, 4, EY)
# 瞳孔高光
circ(cx-5, eyeY-2, 2, WH)
circ(cx+9, eyeY-2, 2, WH)
# 小高光
rect(cx-6, eyeY-3, 1, 1, WH)
rect(cx+8, eyeY-3, 1, 1, WH)

# ===== 腮红 =====
circ(cx-11, eyeY+5, 2, BL)
circ(cx+11, eyeY+5, 2, BL)

# ===== 嘴 =====
line(cx-2, eyeY+7, cx+2, eyeY+7, rgb565(180,120,120), 1)

# ===== 身体 =====
bodyY = cy + 14
# 上衣
rect(cx-9, bodyY, 18, 16, TP)
# 领子白色V领
line(cx, bodyY+1, cx-5, bodyY+6, WH, 2)
line(cx, bodyY+1, cx+5, bodyY+6, WH, 2)
# 领带
rect(cx-1, bodyY+2, 3, 10, TIE)
rect(cx+3, bodyY+6, 2, 4, TIE)

# 裙子
skirtY = bodyY + 14
rect(cx-10, skirtY, 20, 5, SKT)
rect(cx-11, skirtY+1, 22, 3, SKT)

# ===== 手臂 =====
rect(cx-14, bodyY+2, 5, 10, SK)
circ(cx-11, bodyY+2, 3, SK)  # 左手
rect(cx+9, bodyY+2, 5, 10, SK)
circ(cx+11, bodyY+2, 3, SK)   # 右手

# 袖口
rect(cx-14, bodyY, 6, 3, rgb565(80,90,110))
rect(cx+8, bodyY, 6, 3, rgb565(80,90,110))

# ===== 腿 =====
legY = skirtY + 4
rect(cx-6, legY, 5, 10, SK)
rect(cx+1, legY, 5, 10, SK)

# 长靴
rect(cx-7, legY+8, 7, 8, SH)
rect(cx, legY+8, 7, 8, SH)
# 靴口白边
rect(cx-7, legY+8, 7, 1, WH)
rect(cx, legY+8, 7, 1, WH)

# 01 标记 (左臂)
rect(cx-10, bodyY+4, 2, 1, rgb565(100,210,200))
rect(cx-10, bodyY+5, 2, 1, rgb565(100,210,200))

# 生成 C 数组
pixels = []
for y in range(H):
    for x in range(W):
        pixels.append(canvas[y][x])

# 输出 C 头文件
print("// 初音未来像素画 56x80 RGB565 — 自动生成")
print(f"#define MIKU_W 56")
print(f"#define MIKU_H 80")
print("const uint16_t miku_sprite[MIKU_W * MIKU_H] PROGMEM = {")
for i in range(0, len(pixels), 16):
    chunk = pixels[i:i+16]
    hexes = ', '.join(f'0x{v:04X}' for v in chunk)
    print(f"  {hexes},")
print("};")
