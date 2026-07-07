"""
干净像素初音 — 64x96，简洁线条+纯色块，适配TFT小屏
设计目标: 一眼认出初音，无噪点
"""
W, H = 64, 96

def rgb565(r,g,b):
    return ((r>>3)<<11)|((g>>2)<<5)|(b>>3)

BG = 0x0862  # 背景
T = BG       # 透明=背景

# 调色板 — 精确选取初音配色
SK = rgb565(255,218,190)  # 肤色
HC = rgb565(57,197,187)   # 初音发色(主)
HD = rgb565(28,145,135)   # 深发色
HL = rgb565(130,235,225)  # 高光发色
EY = rgb565(45,170,160)   # 眼睛
WH = rgb565(255,255,255)  # 白色
BK = rgb565(25,25,35)     # 黑色
BL = rgb565(255,175,175)  # 腮红
RD = rgb565(220,50,50)    # 红色
HP = rgb565(160,165,175)  # 耳机灰
H2 = rgb565(210,215,225)  # 耳机高光
TP = rgb565(55,65,85)     # 上衣深灰
T2 = rgb565(80,90,110)    # 上衣浅
SKT= rgb565(65,75,95)     # 裙子色
SH = rgb565(65,55,45)     # 靴子
TIE= rgb565(57,197,187)   # 领带(同发色)
N1 = rgb565(130,240,225)  # 音符
MOU= rgb565(190,130,130)  # 嘴唇

canvas = [[BG for _ in range(W)] for _ in range(H)]

def p(x,y,c):
    if 0<=x<W and 0<=y<H and c!=T: canvas[y][x]=c

def fill(x,y,w,h,c):
    for dy in range(h):
        for dx in range(w): p(x+dx,y+dy,c)

def circ(cx,cy,r,c,f=True):
    for dy in range(-r,r+1):
        for dx in range(-r,r+1):
            if dx*dx+dy*dy <= r*r+(1 if f else -r):
                p(cx+dx,cy+dy,c)

def hline(x,y,w,c): fill(x,y,w,1,c)
def vline(x,y,h,c): fill(x,y,1,h,c)

# ==========================================
# 初音未来 64x96 像素画
# ==========================================
cx, fy = W//2, 24  # 脸中心

# === 超长双马尾 (从头顶延伸到画面底部) ===
# 左马尾上段 (从头部向左下延伸)
fill(cx-14,fy-12, 8,28, HC)
fill(cx-16,fy+14, 10,24, HC)
fill(cx-18,fy+34, 12,20, HC)
fill(cx-17,fy+50, 10,18, HC)
fill(cx-15,fy+64, 8,16, HC)
fill(cx-13,fy+76, 6,12, HC)
fill(cx-12,fy+84, 4,8, HD)   # 发尾深色
# 马尾高光
vline(cx-12,fy+16,40, HL)
vline(cx-10,fy+58,18, HL)

# 右马尾上段
fill(cx+6,fy-12, 8,28, HC)
fill(cx+6,fy+14, 10,24, HC)
fill(cx+6,fy+34, 12,20, HC)
fill(cx+7,fy+50, 10,18, HC)
fill(cx+7,fy+64, 8,16, HC)
fill(cx+7,fy+76, 6,12, HC)
fill(cx+8,fy+84, 4,8, HD)
vline(cx+10,fy+16,40, HL)
vline(cx+8,fy+58,18, HL)

# === 刘海 ===
fill(cx-16,fy-16, 32,6, HC)   # 顶部
fill(cx-18,fy-12, 8,10, HC)   # 左鬓
fill(cx+10,fy-12, 8,10, HC)   # 右鬓
# M字刘海
fill(cx-8,fy-22, 4,8, HC)
fill(cx-3,fy-24, 6,8, HC)
fill(cx+4,fy-22, 4,8, HC)
# 补充刘海
fill(cx-14,fy-14, 28,4, HC)
# 侧发垂落
vline(cx-20,fy-4,16, HC)
vline(cx+19,fy-4,16, HC)

# === 耳机 ===
fill(cx-19,fy-9, 38,2, HP)    # 头梁
fill(cx-20,fy-12, 6,10, HP)   # 左耳罩
fill(cx+14,fy-12, 6,10, HP)   # 右耳罩
fill(cx-18,fy-10, 4,6, H2)    # 耳罩高光
fill(cx+16,fy-10, 4,6, H2)

# === 脸 ===
circ(cx,fy,11, SK)
circ(cx,fy,11, rgb565(190,165,145), False)

# === 眼睛 (初音标志性大眼) ===
eyeY = fy - 1
circ(cx-6,eyeY, 5, EY)
circ(cx-6,eyeY, 5, rgb565(18,120,110), False)
circ(cx-4,eyeY-2, 2, WH)
p(cx-3,eyeY-3, WH)
# 右眼
circ(cx+6,eyeY, 5, EY)
circ(cx+6,eyeY, 5, rgb565(18,120,110), False)
circ(cx+8,eyeY-2, 2, WH)
p(cx+9,eyeY-3, WH)

# === 腮红 ===
circ(cx-10,eyeY+4, 3, BL)
circ(cx+10,eyeY+4, 3, BL)

# === 嘴 ===
hline(cx-2,eyeY+6, 4, MOU)

# === 身体 (水手服) ===
by = fy + 14
fill(cx-9,by, 18,16, TP)      # 上衣
# V领白线
hline(cx-3,by+1, 6, WH)
p(cx-1,by+2, WH)
p(cx+1,by+2, WH)
p(cx,by+3, WH)
# 领带
fill(cx-1,by+2, 3,12, TIE)
fill(cx+2,by+5, 2,6, TIE)

# === 裙子 ===
sy = by + 15
fill(cx-10,sy, 20,3, SKT)
fill(cx-11,sy+1, 22,3, SKT)

# === 手臂 ===
fill(cx-14,by+2, 5,12, SK)
circ(cx-11,by+2, 3, SK)
fill(cx+9,by+2, 5,12, SK)
circ(cx+11,by+2, 3, SK)
# 袖口
fill(cx-15,by, 7,3, T2)
fill(cx+8,by, 7,3, T2)

# 01标记
hline(cx-12,by+3, 3, rgb565(100,210,200))
hline(cx-12,by+4, 3, rgb565(100,210,200))
p(cx-11,by+5, rgb565(100,210,200))

# === 腿和靴 ===
ly = sy + 5
fill(cx-6,ly, 5,10, SK)
fill(cx+1,ly, 5,10, SK)
fill(cx-7,ly+9, 7,9, SH)
fill(cx,ly+9, 7,9, SH)
hline(cx-7,ly+9, 7, WH)
hline(cx,ly+9, 7, WH)

# === 音符特效 ===
noteX = cx + 22
noteY = fy - 12
circ(noteX, noteY, 2, N1)
vline(noteX+1, noteY-6, 5, N1)
circ(noteX-8, noteY+10, 1, N1)

# ===== 输出 =====
print(f"// Miku Clean {W}x{H} RGB565")
print(f"#define MIKU_W {W}\n#define MIKU_H {H}")
print("const uint16_t miku_sprite[MIKU_W * MIKU_H] PROGMEM = {")
pixels = []
for y in range(H):
    for x in range(W):
        pixels.append(canvas[y][x])
for i in range(0, len(pixels), 16):
    chunk = pixels[i:i+16]
    print("  " + ", ".join(f"0x{v:04X}" for v in chunk) + ",")
print("};")
sprite_px = sum(1 for v in pixels if v != BG)
print(f"// Stats: {W*H} total, {sprite_px} sprite ({100*sprite_px/(W*H):.0f}%)")
