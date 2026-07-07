"""
初音未来像素画 v3 — 56×96 大尺寸，精确绘制
重点: 超长双马尾 + M字刘海 + 耳机 + 水手服
使用逐行精确像素填充
"""
W, H = 56, 96

def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

# 调色板
BG = 0x0862
SK = rgb565(255,220,195)
HA = rgb565(57,197,187)    # 初音绿
HD = rgb565(28,145,135)    # 深绿(阴影)
HL = rgb565(120,232,222)   # 浅绿(高光)
EY = rgb565(45,170,160)
WH = rgb565(255,255,255)
BK = rgb565(25,25,35)
BL = rgb565(255,175,175)
RD = rgb565(225,50,50)
HP = rgb565(160,165,175)
HLT= rgb565(210,215,225)
TP = rgb565(55,65,85)
SKT= rgb565(65,75,95)
SH = rgb565(65,55,45)
TIE= rgb565(57,197,187)
ARM= rgb565(80,90,110)
MOU= rgb565(190,130,130)

canvas = [[BG for _ in range(W)] for _ in range(H)]

def p(x,y,c):
    if 0<=x<W and 0<=y<H: canvas[y][x]=c

def fill(x,y,w,h,c):
    for dy in range(h):
        for dx in range(w):
            p(x+dx,y+dy,c)

def circ(cx,cy,r,c,fill_only=True):
    for dy in range(-r,r+1):
        for dx in range(-r,r+1):
            d2=dx*dx+dy*dy
            if fill_only and d2<=r*r: p(cx+dx,cy+dy,c)
            elif not fill_only and r*r-2*r<=d2<=r*r+2: p(cx+dx,cy+dy,c)

def hline(x,y,w,c): fill(x,y,w,1,c)

def miku():
    cx, fy = W//2, 22  # 脸中心

    # ====== 超长双马尾 (ICONIC!) ======
    # 左马尾 - 从耳侧垂下，几乎到画面底部
    pts_left = [
        # x, y 偏移 (从左耳位置开始)
        (-16,-6),(-18,0),(-20,8),(-22,18),(-23,28),(-22,38),(-20,48),(-18,58),(-16,68),(-14,76),(-12,82),(-10,88)
    ]
    for i in range(len(pts_left)-1):
        x1,y1 = cx+pts_left[i][0], fy+pts_left[i][1]
        x2,y2 = cx+pts_left[i+1][0], fy+pts_left[i+1][1]
        # 画粗马尾 (8-10px 宽)
        tw = 10 - i//2  # 逐渐变细
        if tw < 4: tw = 4
        # 简化: 用矩形段
        mx = (x1+x2)//2
        my = (y1+y2)//2
        fill(mx-tw//2, my-3, tw, 8, HA)
        # 高光
        if i % 2 == 0: hline(mx-tw//2+2, my, tw-4, HL)

    # 补充左马尾底部
    fill(cx-20, fy+25, 10, 50, HA)
    fill(cx-18, fy+70, 7, 20, HA)
    fill(cx-16, fy+85, 5, 6, HD)
    # 左马尾高光线
    for yy in range(fy+30, fy+75, 3):
        hline(cx-16, yy, 2, HL)

    # 右马尾
    fill(cx+10, fy+25, 10, 50, HA)
    fill(cx+11, fy+70, 7, 20, HA)
    fill(cx+11, fy+85, 5, 6, HD)
    for yy in range(fy+30, fy+75, 3):
        hline(cx+14, yy, 2, HL)

    # ====== 刘海 ======
    fill(cx-14, fy-15, 28, 7, HA)    # 主刘海
    fill(cx-16, fy-10, 7, 8, HA)     # 左鬓
    fill(cx+9, fy-10, 7, 8, HA)      # 右鬓
    # M字刘海
    fill(cx-6, fy-19, 3, 7, HA)
    fill(cx-2, fy-21, 4, 8, HA)
    fill(cx+3, fy-19, 3, 7, HA)
    # 侧发
    fill(cx-18, fy-4, 5, 14, HA)
    fill(cx+13, fy-4, 5, 14, HA)
    # 发顶
    fill(cx-8, fy-23, 16, 5, HA)

    # ====== 耳机 ======
    fill(cx-17, fy-9, 34, 3, HP)
    fill(cx-19, fy-11, 6, 9, HP)
    fill(cx+13, fy-11, 6, 9, HP)
    fill(cx-17, fy-10, 4, 6, HLT)
    fill(cx+15, fy-10, 4, 6, HLT)

    # ====== 脸 ======
    circ(cx, fy, 11, SK)
    circ(cx, fy, 11, rgb565(190,170,150), False)

    # ====== 眼睛 ======
    ey = fy - 2
    # 左眼
    circ(cx-6, ey, 5, EY)
    circ(cx-6, ey, 5, rgb565(20,120,110), False)
    circ(cx-4, ey-2, 2, WH)  # 高光
    p(cx-3, ey-3, WH)
    p(cx-7, ey, WH)           # 眼角高光
    # 右眼
    circ(cx+6, ey, 5, EY)
    circ(cx+6, ey, 5, rgb565(20,120,110), False)
    circ(cx+8, ey-2, 2, WH)
    p(cx+9, ey-3, WH)
    p(cx+5, ey, WH)

    # ====== 腮红 ======
    circ(cx-10, ey+5, 3, BL)
    circ(cx+10, ey+5, 3, BL)

    # ====== 嘴 ======
    hline(cx-2, ey+7, 4, MOU)

    # ====== 身体 ======
    by = fy + 13
    fill(cx-9, by, 18, 16, TP)    # 上衣
    # V领
    hline(cx-3, by+1, 6, WH)
    p(cx-1, by+2, WH)
    p(cx+1, by+2, WH)
    p(cx, by+3, WH)
    # 领带
    fill(cx-2, by+3, 3, 10, TIE)
    fill(cx+2, by+6, 2, 4, TIE)

    # 裙子
    sy = by + 15
    fill(cx-10, sy, 20, 3, SKT)
    fill(cx-11, sy+1, 22, 3, SKT)

    # ====== 手臂 ======
    fill(cx-14, by+2, 5, 12, SK)
    circ(cx-11, by+2, 3, SK)
    fill(cx+9, by+2, 5, 12, SK)
    circ(cx+11, by+2, 3, SK)
    fill(cx-15, by, 7, 3, ARM)    # 袖口
    fill(cx+8, by, 7, 3, ARM)

    # 01
    hline(cx-11, by+3, 3, rgb565(100,210,200))
    hline(cx-11, by+4, 3, rgb565(100,210,200))

    # ====== 腿和靴 ======
    ly = sy + 5
    fill(cx-6, ly, 5, 10, SK)
    fill(cx+1, ly, 5, 10, SK)
    fill(cx-7, ly+9, 7, 8, SH)
    fill(cx, ly+9, 7, 8, SH)
    hline(cx-7, ly+9, 7, WH)
    hline(cx, ly+9, 7, WH)

    # ====== 音符特效 ======
    noteX, noteY = cx+22, fy-10
    circ(noteX, noteY, 2, rgb565(120,240,225))
    fill(noteX+1, noteY-6, 1, 5, rgb565(120,240,225))
    circ(noteX-6, noteY+8, 1, rgb565(150,245,230))

    # ====== 高光线条增强 ======
    # 左侧发高光
    for yy in range(fy-4, fy+12, 3):
        p(cx-17, yy, HL)

miku()

# 输出
print(f"// Miku Pixel Art {W}x{H} RGB565")
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
print(f"// Stats: {len(pixels)} total, {len(pixels)-pixels.count(BG)} sprite pixels")
