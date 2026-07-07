"""
极简初音Q版 — 80x100, 只画核心要素: 圆脸+大眼+超长双马尾+刘海
无复杂渐变、纯色块
"""
W, H = 80, 100

def rgb565(r,g,b):
    return ((r>>3)<<11)|((g>>2)<<5)|(b>>3)

BG = 0x0862
SK = rgb565(255,220,195)   # 肤色
HA = rgb565(57,197,187)    # 初音绿
HD = rgb565(28,145,135)    # 深绿
HL = rgb565(130,235,225)   # 高光绿
EY = rgb565(45,170,160)    # 眼睛
WH = rgb565(255,255,255)
BK = rgb565(20,20,30)
BL = rgb565(255,175,175)   # 腮红
HP = rgb565(160,165,175)   # 耳机
T2 = rgb565(210,215,225)   # 耳机高光
TP = rgb565(55,65,85)      # 衣服
SKT= rgb565(60,70,90)      # 裙子
N1 = rgb565(140,240,225)   # 音符
MOU= rgb565(190,130,130)

canvas = [[BG for _ in range(W)] for _ in range(H)]

def p(x,y,c):
    if 0<=x<W and 0<=y<H: canvas[y][x]=c

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

cx, fy = W//2, 28

# === 超长双马尾 ===
# 左马尾
fill(cx-16,fy-10, 10,30, HA)
fill(cx-18,fy+16, 12,24, HA)
fill(cx-17,fy+36, 10,22, HA)
fill(cx-15,fy+54, 8,18, HA)
fill(cx-13,fy+68, 6,14, HA)
fill(cx-12,fy+78, 4,10, HA)
fill(cx-10,fy+86, 3,6, HD)
vline(cx-13,fy+18,50, HL)

# 右马尾
fill(cx+6,fy-10, 10,30, HA)
fill(cx+6,fy+16, 12,24, HA)
fill(cx+7,fy+36, 10,22, HA)
fill(cx+7,fy+54, 8,18, HA)
fill(cx+7,fy+68, 6,14, HA)
fill(cx+8,fy+78, 4,10, HA)
fill(cx+8,fy+86, 3,6, HD)
vline(cx+11,fy+18,50, HL)

# === 刘海 ===
fill(cx-16,fy-16, 32,5, HA)
fill(cx-18,fy-12, 6,10, HA)
fill(cx+12,fy-12, 6,10, HA)
# M字
fill(cx-8,fy-20, 3,7, HA)
fill(cx-2,fy-22, 5,7, HA)
fill(cx+5,fy-20, 3,7, HA)
vline(cx-20,fy-2,14, HA)
vline(cx+19,fy-2,14, HA)

# === 耳机 ===
fill(cx-18,fy-6, 36,2, HP)
fill(cx-19,fy-9, 6,9, HP)
fill(cx+13,fy-9, 6,9, HP)
fill(cx-17,fy-7, 4,5, T2)
fill(cx+15,fy-7, 4,5, T2)

# === 脸 ===
circ(cx,fy,12, SK)
circ(cx,fy,12, rgb565(185,160,140), False)

# === 眼睛 ===
ey = fy-1
circ(cx-6,ey, 5, EY)
circ(cx-6,ey, 5, rgb565(15,115,105), False)
circ(cx-4,ey-2, 2, WH)
p(cx-4,ey-3, WH)
circ(cx+6,ey, 5, EY)
circ(cx+6,ey, 5, rgb565(15,115,105), False)
circ(cx+8,ey-2, 2, WH)
p(cx+8,ey-3, WH)

# === 腮红 ===
circ(cx-10,ey+4, 3, BL)
circ(cx+10,ey+4, 3, BL)

# === 嘴 ===
hline(cx-2,ey+6, 4, MOU)

# === 身体 ===
by = fy+15
fill(cx-9,by, 18,14, TP)
hline(cx-2,by+1, 6, WH)
p(cx-1,by+2, WH); p(cx+1,by+2, WH)
fill(cx,by+3, 1,8, HA)  # 领带

# === 腿 ===
sy = by+13
fill(cx-5,sy+1, 4,8, SK)
fill(cx+1,sy+1, 4,8, SK)
fill(cx-6,sy+8, 6,6, rgb565(60,50,40))
fill(cx,sy+8, 6,6, rgb565(60,50,40))

# === 音符 ===
nx, ny = cx+24, fy-10
circ(nx,ny, 2, N1)
vline(nx+1,ny-6,5, N1)

# 输出
print(f"// Miku Simple {W}x{H}\n#define MIKU_W {W}\n#define MIKU_H {H}")
print("const uint16_t miku_sprite[MIKU_W * MIKU_H] PROGMEM = {")
pixels = [canvas[y][x] for y in range(H) for x in range(W)]
for i in range(0,len(pixels),16):
    print("  "+", ".join(f"0x{v:04X}" for v in pixels[i:i+16])+",")
print("};")
sp = sum(1 for v in pixels if v!=BG)
print(f"// {sp}/{W*H} ({100*sp/(W*H):.0f}%)")
