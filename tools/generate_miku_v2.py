"""
初音未来像素画 v2 — 48×72 手绘像素，每个像素精确定位
输出 RGB565 C 数组
"""
W, H = 48, 72

def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

# 调色板
BG = 0x0862     # 深蓝背景
SK = rgb565(255,218,185)  # 肤色
HA = rgb565(57,197,187)   # 初音绿
HD = rgb565(30,150,140)   # 深初音绿
HL = rgb565(120,230,220)  # 浅初音绿
EY = rgb565(45,170,160)   # 眼
WH = rgb565(255,255,255)
BK = rgb565(30,30,40)
BL = rgb565(255,180,180)  # 腮红
RD = rgb565(220,50,50)
HP = rgb565(160,165,175)  # 耳机
HLT= rgb565(210,215,225)  # 耳机高光
TP = rgb565(55,65,85)     # 上衣
SKT= rgb565(65,75,95)     # 裙子
SH = rgb565(65,55,45)     # 靴
TIE= rgb565(57,197,187)   # 领带
ARM= rgb565(80,90,110)    # 袖口

canvas = [[BG for _ in range(W)] for _ in range(H)]

def p(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        canvas[y][x] = c

def rect(x, y, w, h, c):
    for dy in range(h):
        for dx in range(w):
            p(x+dx, y+dy, c)

def circ(cx, cy, r, c, fill=True):
    for dy in range(-r, r+1):
        for dx in range(-r, r+1):
            d2 = dx*dx + dy*dy
            if fill and d2 <= r*r:
                p(cx+dx, cy+dy, c)
            elif not fill and r*r-3*r <= d2 <= r*r+3:
                p(cx+dx, cy+dy, c)

def hline(x, y, w, c):
    rect(x, y, w, 1, c)

def vline(x, y, h, c):
    rect(x, y, 1, h, c)

def tri(x1,y1,x2,y2,x3,y3,c):
    minx, maxx = max(0,min(x1,x2,x3)), min(W-1,max(x1,x2,x3))
    miny, maxy = max(0,min(y1,y2,y3)), min(H-1,max(y1,y2,y3))
    for y in range(miny, maxy+1):
        for x in range(minx, maxx+1):
            d1 = (x-x2)*(y1-y2) - (x1-x2)*(y-y2)
            d2 = (x-x3)*(y2-y3) - (x2-x3)*(y-y3)
            d3 = (x-x1)*(y3-y1) - (x3-x1)*(y-y1)
            neg = (d1<0) or (d2<0) or (d3<0)
            pos = (d1>0) or (d2>0) or (d3>0)
            if not (neg and pos):
                p(x, y, c)

# =============== 双马尾 (最底层) ===============
# 左马尾 — 长及腰部
tri(12,12, 2,32, 8,68, HA)     # 左马尾主体
tri(14,10, 4,32, 10,68, HA)
rect(3,62, 8,10, HA)           # 发尾
rect(3,68, 7,4, HD)            # 发尾深色
vline(6,55,15, HL)             # 高光

# 右马尾
tri(W-12,12, W-2,32, W-8,68, HA)
tri(W-14,10, W-4,32, W-10,68, HA)
rect(W-11,62, 8,10, HA)
rect(W-10,68, 7,4, HD)
vline(W-6,55,15, HL)

# 马尾内部层次
vline(5,40,24, HD)  # 左马尾内阴影
vline(W-5,40,24, HD)

# =============== 刘海 ===============
cx = W // 2
faceY = 18
rect(cx-14, faceY-14, 28, 7, HA)    # 主刘海
rect(cx-16, faceY-10, 7, 8, HA)     # 左鬓
rect(cx+9, faceY-10, 7, 8, HA)      # 右鬓
# M字刘海尖
rect(cx-6, faceY-18, 2, 6, HA)
rect(cx-1, faceY-20, 2, 8, HA)
rect(cx+4, faceY-18, 2, 6, HA)
# 侧发垂下
rect(cx-18, faceY-4, 4, 10, HA)
rect(cx+14, faceY-4, 4, 10, HA)

# =============== 耳机 ===============
rect(cx-18, faceY-8, 36, 2, HP)     # 头梁
rect(cx-20, faceY-10, 5, 8, HP)     # 左耳罩
rect(cx+15, faceY-10, 5, 8, HP)     # 右耳罩
rect(cx-18, faceY-9, 3, 5, HLT)     # 耳罩高光
rect(cx+17, faceY-9, 3, 5, HLT)

# =============== 脸 ===============
circ(cx, faceY, 10, SK)             # 脸蛋
circ(cx, faceY, 10, rgb565(190,165,145), False)  # 轮廓线

# =============== 眼睛 ===============
eyeY = faceY - 1
# 左眼
circ(cx-5, eyeY, 4, EY)
circ(cx-5, eyeY, 4, rgb565(20,130,120), False)
circ(cx-4, eyeY-2, 2, WH)           # 主高光
p(cx-3, eyeY-3, WH)                 # 小高光
# 右眼
circ(cx+5, eyeY, 4, EY)
circ(cx+5, eyeY, 4, rgb565(20,130,120), False)
circ(cx+6, eyeY-2, 2, WH)
p(cx+7, eyeY-3, WH)

# =============== 腮红 ===============
circ(cx-9, eyeY+4, 2, BL)
circ(cx+9, eyeY+4, 2, BL)

# =============== 嘴 ===============
hline(cx-1, eyeY+6, 3, rgb565(190,130,130))
p(cx+2, eyeY+5, rgb565(210,150,150))

# =============== 身体 ===============
bodyY = faceY + 12
# 上衣
rect(cx-8, bodyY, 16, 14, TP)
# V领白线
hline(cx-3, bodyY+1, 6, WH)
p(cx-2, bodyY+2, WH)
p(cx+1, bodyY+2, WH)
# 领带
rect(cx-1, bodyY+2, 2, 9, TIE)
rect(cx+2, bodyY+5, 2, 4, TIE)

# 裙子
skirtY = bodyY + 13
rect(cx-9, skirtY, 18, 3, SKT)
rect(cx-10, skirtY+1, 20, 2, SKT)

# =============== 手臂 ===============
rect(cx-13, bodyY+1, 4, 10, SK)
circ(cx-11, bodyY+1, 2, SK)
rect(cx+9, bodyY+1, 4, 10, SK)
circ(cx+11, bodyY+1, 2, SK)
# 袖口
rect(cx-14, bodyY, 6, 2, ARM)
rect(cx+8, bodyY, 6, 2, ARM)

# 01 标记
hline(cx-10, bodyY+3, 2, rgb565(100,210,200))
hline(cx-10, bodyY+4, 2, rgb565(100,210,200))
p(cx-9, bodyY+5, rgb565(100,210,200))

# =============== 腿 ===============
legY = skirtY + 4
rect(cx-5, legY, 4, 8, SK)
rect(cx+1, legY, 4, 8, SK)

# 长靴
rect(cx-6, legY+7, 6, 7, SH)
rect(cx, legY+7, 6, 7, SH)
hline(cx-6, legY+7, 6, WH)   # 靴口白边
hline(cx, legY+7, 6, WH)

# =============== 音符特效 ===============
p(cx+18, faceY-8, rgb565(100,230,215))
p(cx+19, faceY-9, rgb565(100,230,215))
p(cx+20, faceY-8, rgb565(100,230,215))
p(cx+17, faceY-10, rgb565(140,240,225))
p(cx+18, faceY-13, rgb565(140,240,225))
p(cx+19, faceY-12, rgb565(140,240,225))

# 输出 C 数组
print("// Hatsune Miku Pixel Art 48x72 RGB565")
print(f"#define MIKU_W {W}")
print(f"#define MIKU_H {H}")
print("const uint16_t miku_sprite[MIKU_W * MIKU_H] PROGMEM = {")
pixels = []
for y in range(H):
    for x in range(W):
        pixels.append(canvas[y][x])
for i in range(0, len(pixels), 16):
    chunk = pixels[i:i+16]
    print("  " + ", ".join(f"0x{v:04X}" for v in chunk) + ",")
print("};")
