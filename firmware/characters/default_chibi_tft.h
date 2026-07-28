/*
 * ================================================================
 *  TFT 彩色 Q 版角色 - "安小盾" (An-chan)
 *  Default Chibi for TFT Color Display
 *
 *  为 TTGO T-Display (135x240 TFT) 设计的程序化彩色角色
 *  支持 8 种表情 + 3 帧眨眼 + 特效动画
 *
 *  绘制方式: 全部使用 GFX 几何体 (无需图片素材)
 * ================================================================
 */

#ifndef DEFAULT_CHIBI_TFT_H
#define DEFAULT_CHIBI_TFT_H

#include <TFT_eSPI.h>

// ==================== 表情常量 (与固件一致) ====================
#define TFT_EXP_IDLE      0
#define TFT_EXP_HAPPY     1
#define TFT_EXP_WORKING   2
#define TFT_EXP_WORRIED   3
#define TFT_EXP_ANGRY     4
#define TFT_EXP_SLEEP     5
#define TFT_EXP_LOVE      6
#define TFT_EXP_GREETING  7

// ==================== 角色颜色 (RGB565) ====================
// 肤色 - 暖桃色
#define C_SKIN        0xFD75
#define C_SKIN_SHADOW 0xE493
// 发色 - 巧克力棕
#define C_HAIR        0x6A41
#define C_HAIR_LIGHT  0x8C83
#define C_HAIR_DARK   0x38E6
// 眼睛
#define C_EYE_WHITE   0xFFFF
#define C_EYE_DARK    0x1082
#define C_EYE_BLUE    0x4B7F
// 嘴巴
#define C_MOUTH       0x528A
// 腮红
#define C_BLUSH       0xFAC9
// 发饰 - 红色蝴蝶结
#define C_BOW         0xF9A6
#define C_BOW_DARK    0xD0E5
// 制服/衣领
#define C_UNIFORM     0x2A4F
#define C_COLLAR      0xFFFF
// 特效
#define C_HEART       0xF8C7
#define C_SWEAT       0x9D1F
#define C_STAR        0xFF39

class DefaultChibiTFT {
public:
  // ==================== 主绘制函数 ====================
  // gfx: TFT_eSPI 或 TFT_eSprite 指针
  // cx, cy: 角色头部中心坐标
  // expression: 0-7 表情
  // blinkFrame: 0=睁眼 1=半闭 2=全闭
  // showHeart/showSweat: 特效开关
  // zzzOffset: Zzz 浮动偏移 (0-3)
  // wavePhase: 挥手相位 (0-3)
  // breathOffset: 呼吸浮动偏移 (像素)
  static void draw(TFT_eSprite* gfx, int cx, int cy,
                   uint8_t expression, uint8_t blinkFrame = 0,
                   bool showHeart = false, bool showSweat = false,
                   int zzzOffset = 0, int wavePhase = 0,
                   int breathOffset = 0) {

    int by = cy + breathOffset;  // 呼吸偏移

    // 绘制顺序: 后层 → 前层
    drawBody(gfx, cx, by);           // 身体 (后)
    drawHairBack(gfx, cx, by);       // 后发
    drawFace(gfx, cx, by);           // 脸型
    drawBlush(gfx, cx, by, expression, blinkFrame);  // 腮红
    drawEyes(gfx, cx, by, expression, blinkFrame);   // 眼睛
    drawMouth(gfx, cx, by, expression);              // 嘴巴
    drawHairFront(gfx, cx, by);      // 前发 (刘海)
    drawHairAccessory(gfx, cx, by);  // 发饰

    // 特效
    if (showHeart) drawHeartEffect(gfx, cx + 28, by - 35);
    if (showSweat) drawSweatEffect(gfx, cx + 22, by - 40);
    if (expression == TFT_EXP_SLEEP || expression == TFT_EXP_GREETING) {
      drawCheekMark(gfx, cx, by, expression);
    }

    // Zzz (睡觉时)
    if (expression == TFT_EXP_SLEEP) {
      drawZZZEffect(gfx, cx + 28, by - 38 - zzzOffset * 4);
    }
  }

  // ==================== 状态图标 (角色下方) ====================
  static void drawStatusIcon(TFT_eSprite* gfx, int cx, int baseY,
                              const String& secLevel, unsigned long now) {
    int ix = cx - 8;
    int iy = baseY;

    if (secLevel == "safe") {
      // 盾牌 ✓
      gfx->fillRoundRect(ix, iy, 16, 18, 4, 0x07E0);  // green shield
      gfx->setTextColor(0xFFFF, 0x07E0);
      gfx->setTextSize(1);
      gfx->drawString("S", ix + 4, iy + 3);
    } else if (secLevel == "warning") {
      // 警告三角 (闪烁)
      bool flash = (now / 400) % 2;
      uint16_t wc = flash ? 0xFD20 : 0x632C;
      gfx->fillTriangle(ix + 8, iy, ix, iy + 16, ix + 16, iy + 16, wc);
      gfx->setTextColor(0x0000, wc);
      gfx->drawString("!", ix + 5, iy + 4);
    } else {  // danger
      // 红色感叹号 (脉冲)
      int sz = 8 + (sin(now * 0.01) + 1) * 2;
      gfx->fillCircle(ix + 8, iy + 8, sz, 0xF800);
      gfx->setTextColor(0xFFFF, 0xF800);
      gfx->drawString("!", ix + 5, iy + 3);
    }
  }

  // ==================== 气泡 ====================
  static void drawBubble(TFT_eSprite* gfx, int x, int y,
                          const String& text) {
    if (text.length() == 0) return;
    int tw = text.length() * 6 + 12;
    int bw = constrain(tw, 30, 120);
    int bh = 18;

    if (x + bw > 135) x = 135 - bw;
    if (x < 2) x = 2;
    if (y - bh < 2) y = bh + 4;

    // 气泡背景
    gfx->fillRoundRect(x, y - bh, bw, bh, 6, 0xFFFF);
    gfx->drawRoundRect(x, y - bh, bw, bh, 6, 0x632C);
    // 尾巴
    gfx->fillTriangle(x + 18, y, x + 25, y, x + 14, y + 7, 0xFFFF);

    // 文字
    gfx->setTextColor(0x0841, 0xFFFF);
    gfx->setTextSize(1);
    gfx->drawString(text.substring(0, 20), x + 6, y - bh + 3);
  }

private:
  // ==================== 身体 ====================
  static void drawBody(TFT_eSprite* gfx, int cx, int cy) {
    // 肩膀
    int sy = cy + 34;
    gfx->fillRoundRect(cx - 28, sy, 56, 22, 8, C_UNIFORM);
    // 领口
    gfx->fillTriangle(cx - 8, sy, cx + 8, sy, cx, sy + 10, C_COLLAR);
    // 领带/蝴蝶结
    gfx->fillCircle(cx, sy + 6, 3, 0xF800);
  }

  // ==================== 后发 ====================
  static void drawHairBack(TFT_eSprite* gfx, int cx, int cy) {
    // 后脑勺头发 - 比脸大一圈
    gfx->fillCircle(cx - 1, cy - 2, 28, C_HAIR_DARK);
    gfx->fillCircle(cx + 1, cy - 1, 27, C_HAIR);
    // 侧发垂落
    gfx->fillRoundRect(cx - 30, cy - 8, 8, 40, 4, C_HAIR);
    gfx->fillRoundRect(cx + 22, cy - 8, 8, 40, 4, C_HAIR);
  }

  // ==================== 脸型 ====================
  static void drawFace(TFT_eSprite* gfx, int cx, int cy) {
    // 椭圆脸 (用 round rect 近似)
    gfx->fillRoundRect(cx - 22, cy - 24, 44, 50, 18, C_SKIN);
    // 下巴微尖
    gfx->fillCircle(cx, cy + 22, 12, C_SKIN);
  }

  // ==================== 腮红 ====================
  static void drawBlush(TFT_eSprite* gfx, int cx, int cy,
                         uint8_t exp, uint8_t blink) {
    if (exp == TFT_EXP_HAPPY || exp == TFT_EXP_LOVE || exp == TFT_EXP_GREETING) {
      int by = cy + 6;
      for (int side = -1; side <= 1; side += 2) {
        int bx = cx + side * 16;
        gfx->fillCircle(bx, by, 5, C_BLUSH);
        // 高光小点
        gfx->fillCircle(bx - 1, by - 1, 1, 0xFFDA);
      }
    }
  }

  // ==================== 眼睛 ====================
  static void drawEyes(TFT_eSprite* gfx, int cx, int cy,
                        uint8_t exp, uint8_t blink) {
    // 全闭眼 — 画横线
    if (blink == 2) {
      int ey = cy - 4;
      gfx->drawLine(cx - 14, ey, cx - 4, ey, C_MOUTH);
      gfx->drawLine(cx + 4, ey, cx + 14, ey, C_MOUTH);
      gfx->drawLine(cx - 13, ey + 1, cx - 5, ey + 1, C_MOUTH);
      gfx->drawLine(cx + 5, ey + 1, cx + 13, ey + 1, C_MOUTH);
      return;
    }
    // 半闭眼
    if (blink == 1) {
      int ey = cy - 4;
      gfx->drawLine(cx - 13, ey, cx - 5, ey, C_MOUTH);
      gfx->drawLine(cx + 5, ey, cx + 13, ey, C_MOUTH);
      return;
    }

    switch (exp) {
      case TFT_EXP_IDLE:     drawEyesIdle(gfx, cx, cy); break;
      case TFT_EXP_HAPPY:    drawEyesHappy(gfx, cx, cy); break;
      case TFT_EXP_WORKING:  drawEyesWorking(gfx, cx, cy); break;
      case TFT_EXP_WORRIED:  drawEyesWorried(gfx, cx, cy); break;
      case TFT_EXP_ANGRY:    drawEyesAngry(gfx, cx, cy); break;
      case TFT_EXP_SLEEP:    drawEyesSleep(gfx, cx, cy); break;
      case TFT_EXP_LOVE:     drawEyesLove(gfx, cx, cy); break;
      case TFT_EXP_GREETING: drawEyesGreeting(gfx, cx, cy); break;
      default:               drawEyesIdle(gfx, cx, cy); break;
    }
  }

  static void drawEyesIdle(TFT_eSprite* gfx, int cx, int cy) {
    int ey = cy - 4;
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * 10;
      // 白色眼底
      gfx->fillRoundRect(ex - 7, ey - 8, 14, 16, 7, C_EYE_WHITE);
      // 瞳孔 (深色大圆)
      gfx->fillCircle(ex, ey, 5, C_EYE_DARK);
      // 高光
      gfx->fillCircle(ex + 2, ey - 3, 2, C_EYE_WHITE);
      gfx->fillCircle(ex - 1, ey + 1, 1, C_EYE_WHITE);
    }
  }

  static void drawEyesHappy(TFT_eSprite* gfx, int cx, int cy) {
    int ey = cy - 3;
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * 10;
      // ^ ^ 弧形笑眼 (用粗线)
      for (int t = 0; t < 4; t++) {
        gfx->drawLine(ex - 6, ey - 3 + t, ex, ey + 1 + t, C_MOUTH);
        gfx->drawLine(ex + 6, ey - 3 + t, ex, ey + 1 + t, C_MOUTH);
      }
    }
  }

  static void drawEyesWorking(TFT_eSprite* gfx, int cx, int cy) {
    int ey = cy - 3;
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * 10;
      // 小而专注的眼
      gfx->fillRoundRect(ex - 5, ey - 5, 10, 10, 4, C_EYE_WHITE);
      gfx->fillCircle(ex, ey, 3, C_EYE_BLUE);
      gfx->fillCircle(ex + 1, ey - 1, 1, C_EYE_WHITE);
      // 眉毛 (略低)
      gfx->drawLine(ex - 6, ey - 8, ex + 6, ey - 7, C_MOUTH);
      gfx->drawLine(ex - 6, ey - 7, ex + 6, ey - 6, C_MOUTH);
    }
  }

  static void drawEyesWorried(TFT_eSprite* gfx, int cx, int cy) {
    int ey = cy - 4;
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * 10;
      // 大眼
      gfx->fillRoundRect(ex - 7, ey - 7, 14, 14, 6, C_EYE_WHITE);
      gfx->fillCircle(ex, ey, 4, C_EYE_DARK);
      gfx->fillCircle(ex + 1, ey - 2, 2, C_EYE_WHITE);
      // 八字眉
      int dir = side;
      gfx->drawLine(ex - 5, ey - 7, ex - dir * 3, ey - 10, C_MOUTH);
      gfx->drawLine(ex + 5, ey - 7, ex + dir * 3, ey - 10, C_MOUTH);
      gfx->drawLine(ex - 5, ey - 6, ex - dir * 3, ey - 9, C_MOUTH);
      gfx->drawLine(ex + 5, ey - 6, ex + dir * 3, ey - 9, C_MOUTH);
    }
  }

  static void drawEyesAngry(TFT_eSprite* gfx, int cx, int cy) {
    int ey = cy - 4;
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * 10;
      // > < 三角眼
      gfx->fillTriangle(ex - 5, ey - 8, ex + 6, ey - 2,
                        ex - 3, ey + 2, 0xF800);
      gfx->fillCircle(ex, ey - 3, 1, C_EYE_WHITE);
      // 粗怒眉
      gfx->drawLine(ex - 5, ey - 10, ex + 7, ey - 8, C_MOUTH);
      gfx->drawLine(ex - 5, ey - 9, ex + 7, ey - 7, C_MOUTH);
      gfx->drawLine(ex - 5, ey - 8, ex + 7, ey - 6, C_MOUTH);
    }
  }

  static void drawEyesSleep(TFT_eSprite* gfx, int cx, int cy) {
    int ey = cy - 3;
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * 10;
      // 闭眼弧线 (U 形)
      gfx->drawLine(ex - 5, ey, ex + 5, ey, C_MOUTH);
      gfx->drawLine(ex - 4, ey + 1, ex + 4, ey + 1, C_MOUTH);
      // 睫毛
      gfx->drawPixel(ex - 3, ey + 2, C_MOUTH);
      gfx->drawPixel(ex + 3, ey + 2, C_MOUTH);
    }
  }

  static void drawEyesLove(TFT_eSprite* gfx, int cx, int cy) {
    int ey = cy - 4;
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * 10;
      // ♡ 爱心眼 (两个圆+三角)
      gfx->fillCircle(ex - 3, ey - 4, 4, C_HEART);
      gfx->fillCircle(ex + 3, ey - 4, 4, C_HEART);
      gfx->fillTriangle(ex - 5, ey - 2, ex + 5, ey - 2, ex, ey + 4, C_HEART);
      // 白色小高光
      gfx->fillCircle(ex - 2, ey - 4, 1, C_EYE_WHITE);
      gfx->fillCircle(ex + 2, ey - 4, 1, C_EYE_WHITE);
    }
  }

  static void drawEyesGreeting(TFT_eSprite* gfx, int cx, int cy) {
    int ey = cy - 5;
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * 10;
      // 闪闪大眼
      gfx->fillRoundRect(ex - 7, ey - 8, 14, 15, 6, C_EYE_WHITE);
      gfx->fillCircle(ex, ey, 5, C_EYE_BLUE);
      // 星形高光
      drawStar(gfx, ex, ey - 1, 3, C_EYE_WHITE);
      gfx->fillCircle(ex + 2, ey + 2, 1, C_EYE_WHITE);
    }
  }

  // ==================== 嘴巴 ====================
  static void drawMouth(TFT_eSprite* gfx, int cx, int cy, uint8_t exp) {
    int my = cy + 13;
    switch (exp) {
      case TFT_EXP_IDLE:
        // 小微笑
        gfx->drawLine(cx - 4, my, cx, my + 2, C_MOUTH);
        gfx->drawLine(cx + 4, my, cx, my + 2, C_MOUTH);
        break;
      case TFT_EXP_HAPPY:
        // 开口大笑
        gfx->fillRoundRect(cx - 7, my - 2, 14, 9, 4, C_MOUTH);
        gfx->fillRoundRect(cx - 6, my - 1, 12, 4, 2, C_EYE_WHITE);  // 牙齿
        break;
      case TFT_EXP_WORKING:
        // 抿嘴直线
        gfx->drawLine(cx - 5, my + 1, cx + 5, my + 1, C_MOUTH);
        gfx->drawLine(cx - 5, my + 2, cx + 5, my + 2, C_MOUTH);
        break;
      case TFT_EXP_WORRIED:
        // 波浪嘴
        gfx->drawLine(cx - 5, my, cx - 1, my + 2, C_MOUTH);
        gfx->drawLine(cx - 1, my + 2, cx + 2, my - 1, C_MOUTH);
        gfx->drawLine(cx + 2, my - 1, cx + 5, my + 1, C_MOUTH);
        break;
      case TFT_EXP_ANGRY:
        // 锯齿嘴
        gfx->drawLine(cx - 5, my, cx, my + 3, C_MOUTH);
        gfx->drawLine(cx + 5, my, cx, my + 3, C_MOUTH);
        gfx->drawLine(cx - 5, my - 1, cx, my + 2, C_MOUTH);
        gfx->drawLine(cx + 5, my - 1, cx, my + 2, C_MOUTH);
        break;
      case TFT_EXP_SLEEP:
        // 张开的 O 嘴
        gfx->fillCircle(cx, my + 2, 4, C_MOUTH);
        break;
      case TFT_EXP_LOVE:
        // 嘟嘴 ♡
        gfx->fillCircle(cx, my + 1, 3, C_HEART);
        break;
      case TFT_EXP_GREETING:
        // 开怀大笑
        gfx->fillRoundRect(cx - 8, my - 3, 16, 10, 4, C_MOUTH);
        gfx->fillRoundRect(cx - 7, my - 2, 14, 4, 2, C_EYE_WHITE);
        break;
    }
  }

  // ==================== 前发 (刘海) ====================
  static void drawHairFront(TFT_eSprite* gfx, int cx, int cy) {
    // 顶部头发
    gfx->fillCircle(cx, cy - 16, 18, C_HAIR);
    // 刘海主体
    gfx->fillRoundRect(cx - 18, cy - 24, 36, 14, 6, C_HAIR);
    // 锯齿刘海边缘
    for (int i = -2; i <= 2; i++) {
      int fx = cx + i * 7;
      gfx->fillTriangle(fx - 3, cy - 24, fx + 3, cy - 24,
                        fx, cy - 17, C_HAIR_LIGHT);
    }
    // 侧刘海
    gfx->fillTriangle(cx - 19, cy - 20, cx - 10, cy - 24,
                      cx - 14, cy - 8, C_HAIR);
    gfx->fillTriangle(cx + 19, cy - 20, cx + 10, cy - 24,
                      cx + 14, cy - 8, C_HAIR);
  }

  // ==================== 发饰 ====================
  static void drawHairAccessory(TFT_eSprite* gfx, int cx, int cy) {
    // 右侧蝴蝶结
    int bx = cx + 20, by = cy - 18;
    // 左翼
    gfx->fillCircle(bx - 4, by, 5, C_BOW);
    // 右翼
    gfx->fillCircle(bx + 4, by, 5, C_BOW);
    // 中心结
    gfx->fillCircle(bx, by, 3, C_BOW_DARK);
    gfx->fillCircle(bx + 1, by - 1, 2, C_BOW);
  }

  // ==================== 特效绘制 ====================

  static void drawHeartEffect(TFT_eSprite* gfx, int x, int y) {
    // 飘出的小爱心
    gfx->fillCircle(x - 2, y - 1, 2, C_HEART);
    gfx->fillCircle(x + 2, y - 1, 2, C_HEART);
    gfx->fillTriangle(x - 4, y, x + 4, y, x, y + 4, C_HEART);
  }

  static void drawSweatEffect(TFT_eSprite* gfx, int x, int y) {
    // 大水滴
    gfx->fillCircle(x, y + 5, 3, C_SWEAT);
    gfx->fillTriangle(x - 2, y - 1, x + 2, y - 1, x, y + 2, C_SWEAT);
  }

  static void drawZZZEffect(TFT_eSprite* gfx, int x, int y) {
    gfx->setTextColor(0x9D1F, 0x0841);  // blue Zzz on dark bg
    gfx->setTextSize(1);
    gfx->drawString("Z", x, y);
    gfx->drawString("z", x + 7, y - 6);
    gfx->drawString("z", x + 14, y - 12);
  }

  static void drawCheekMark(TFT_eSprite* gfx, int cx, int cy, uint8_t exp) {
    // 脸颊记号 (/// 线条表示睡眠/害羞)
    uint16_t c = (exp == TFT_EXP_SLEEP) ? 0x73AE : 0xFAC9;
    int my = cy + 10;
    for (int side = -1; side <= 1; side += 2) {
      int mx = cx + side * 18;
      for (int i = 0; i < 3; i++) {
        gfx->drawLine(mx - 2, my - 2 + i * 3, mx + 2, my - 3 + i * 3, c);
      }
    }
  }

  static void drawStar(TFT_eSprite* gfx, int cx, int cy, int r, uint16_t color) {
    // 5角星
    for (int i = 0; i < 5; i++) {
      float a = -PI / 2 + i * 2 * PI / 5;
      float b = -PI / 2 + (i * 2 + 1) * PI / 5;
      int x1 = cx + r * cos(a), y1 = cy + r * sin(a);
      int x2 = cx + r * 0.4 * cos(b), y2 = cy + r * 0.4 * sin(b);
      int x3 = cx + r * cos(a + 2 * PI / 5), y3 = cy + r * sin(a + 2 * PI / 5);
      gfx->drawLine(x1, y1, x2, y2, color);
      gfx->drawLine(x3, y3, x2, y2, color);
    }
  }

public:
  // ==================== 表情名称标签 ====================
  static void drawExpressionLabel(TFT_eSprite* gfx, int x, int y, uint8_t exp) {
    gfx->setTextColor(0xD69A, 0x0841);
    gfx->setTextSize(1);
    switch (exp) {
      case TFT_EXP_IDLE:     gfx->drawString(".  .", x, y); break;
      case TFT_EXP_HAPPY:    gfx->drawString("^o^", x, y); break;
      case TFT_EXP_WORKING:  gfx->drawString("._.", x, y); break;
      case TFT_EXP_WORRIED:  gfx->drawString(";_;", x, y); break;
      case TFT_EXP_ANGRY:    gfx->drawString(">_<", x, y); break;
      case TFT_EXP_SLEEP:    gfx->drawString("-_-", x, y); break;
      case TFT_EXP_LOVE:     gfx->drawString("<3_<3", x, y); break;
      case TFT_EXP_GREETING: gfx->drawString("*o*", x, y); break;
    }
  }
};

#endif // DEFAULT_CHIBI_TFT_H
