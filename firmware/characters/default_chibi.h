/*
 * ================================================================
 *  默认二次元角色 - "安小盾" (An-chan)
 *  程序化绘制的 Chibi 风格网络安全守护角色
 *
 *  直接在 OLED 上用 GFX 绘制，无需外部图片
 *  支持 8 种表情切换 + 动画效果
 * ================================================================
 */

#ifndef DEFAULT_CHIBI_H
#define DEFAULT_CHIBI_H

#include <Adafruit_GFX.h>
#include <Arduino.h>

// 角色绘制参数
struct ChibiParams {
  int cx, cy;        // 头部中心
  int headR;         // 头部半径
  int eyeY;          // 眼睛Y坐标
  int eyeSpacing;    // 眼距
  int eyeW, eyeH;    // 眼睛尺寸
  int mouthY;        // 嘴巴Y坐标
  int blushY;        // 腮红Y坐标
};

class DefaultChibi {
public:
  // ==================== 主绘制函数 ====================

  static void draw(Adafruit_GFX* gfx, int x, int y,
                   uint8_t expression, uint8_t blinkFrame = 0,
                   bool showHeart = false, bool showSweat = false,
                   int zzzOffset = 0, int wavePhase = 0) {

    // 如果眨眼中使用闭眼
    uint8_t effectiveExp = (blinkFrame == 2) ? EXP_SLEEP_MOMENT : expression;

    int cx = x + 20, cy = y + 22;  // 头部中心

    // === 头发 (后层) ===
    drawHair(gfx, cx, cy);

    // === 脸型 ===
    drawFace(gfx, cx, cy);

    // === 腮红 ===
    drawBlush(gfx, cx, cy, effectiveExp);

    // === 眼睛 (核心表情) ===
    drawEyes(gfx, cx, cy, effectiveExp, blinkFrame);

    // === 嘴巴 ===
    drawMouth(gfx, cx, cy, effectiveExp);

    // === 特效 ===
    if (showHeart) drawHeartEffect(gfx, cx + 22, cy - 15);
    if (showSweat) drawSweatEffect(gfx, cx + 16, cy - 22);
    if (zzzOffset > 0) drawZZZEffect(gfx, cx + 20, cy - 18 - zzzOffset * 3);
  }

  // ==================== 对话气泡 ====================

  static void drawBubble(Adafruit_GFX* gfx, int charX, int charY,
                          const String& text) {
    // 在角色右侧/上方绘制气泡
    int bx = charX + 30;
    int by = charY - 5;

    // 计算气泡大小
    int textW = text.length() * 6 + 8;  // font size 1
    int bw = constrain(textW, 24, 82);
    int bh = 14;

    // 确保不超出屏幕
    if (bx + bw > 128) bx = 128 - bw;
    if (by < 0) by = 2;

    // 气泡背景
    gfx->fillRoundRect(bx, by, bw, bh, 4, SSD1306_WHITE);
    // 气泡尖角 (指向角色)
    gfx->fillTriangle(bx + 6, by + bh,
                      bx + 10, by + bh,
                      bx + 8, by + bh + 5, SSD1306_WHITE);

    // 文字
    gfx->setTextSize(1);
    gfx->setTextColor(SSD1306_BLACK);
    gfx->setCursor(bx + 4, by + 4);
    gfx->print(text);
    gfx->setTextColor(SSD1306_WHITE);
  }

  // ==================== 情绪气泡 (无文字) ====================

  static void drawEmotionBubble(Adafruit_GFX* gfx, int charX, int charY,
                                 const String& symbol) {
    int bx = charX + 30;
    int by = charY - 5;
    int bw = 20, bh = 14;

    gfx->fillRoundRect(bx, by, bw, bh, 4, SSD1306_WHITE);
    gfx->fillTriangle(bx + 4, by + bh, bx + 8, by + bh,
                      bx + 6, by + bh + 5, SSD1306_WHITE);
    gfx->setTextSize(2);
    gfx->setTextColor(SSD1306_BLACK);
    gfx->setCursor(bx + 2, by - 1);
    gfx->print(symbol);
    gfx->setTextColor(SSD1306_WHITE);
  }

private:
  static const uint8_t EXP_IDLE_MOMENT = 99;

  // ==================== 头发 ====================

  static void drawHair(Adafruit_GFX* gfx, int cx, int cy) {
    // 刘海 (前面)
    gfx->fillRect(cx - 14, cy - 19, 28, 12, SSD1306_WHITE);
    // 侧发
    gfx->fillRect(cx - 18, cy - 14, 6, 22, SSD1306_WHITE);
    gfx->fillRect(cx + 12, cy - 14, 6, 22, SSD1306_WHITE);
    // 顶部弧形
    gfx->fillCircle(cx, cy - 12, 16, SSD1306_WHITE);
    // 刘海锯齿
    for (int i = -3; i <= 3; i++) {
      int fx = cx + i * 5;
      gfx->fillTriangle(fx - 2, cy - 18, fx + 2, cy - 18,
                        fx, cy - 12, SSD1306_WHITE);
    }
    // 蝴蝶结/发饰
    gfx->fillCircle(cx + 16, cy - 14, 4, SSD1306_BLACK);
    gfx->fillCircle(cx + 17, cy - 12, 3, SSD1306_WHITE);
    gfx->fillCircle(cx + 19, cy - 16, 3, SSD1306_BLACK);
    gfx->fillCircle(cx + 18, cy - 14, 2, SSD1306_WHITE);
  }

  // ==================== 脸型 ====================

  static void drawFace(Adafruit_GFX* gfx, int cx, int cy) {
    // 椭圆脸
    gfx->fillRoundRect(cx - 16, cy - 16, 32, 34, 14, SSD1306_WHITE);
    // 反色瞳孔区域 (方便后续画眼睛)
    // 留白
  }

  // ==================== 眼睛 ====================

  static void drawEyes(Adafruit_GFX* gfx, int cx, int cy, uint8_t exp, uint8_t blink) {
    int eyeY = cy - 2;
    int eyeSpacing = 6;

    // 眨眼帧: 直接画横线
    if (blink == 1) {  // 半闭
      gfx->drawLine(cx - eyeSpacing - 4, eyeY, cx - eyeSpacing + 4, eyeY, SSD1306_BLACK);
      gfx->drawLine(cx + eyeSpacing - 4, eyeY, cx + eyeSpacing + 4, eyeY, SSD1306_BLACK);
      return;
    }
    if (blink == 2) {  // 全闭
      gfx->drawLine(cx - eyeSpacing - 5, eyeY, cx - eyeSpacing + 5, eyeY, SSD1306_BLACK);
      gfx->drawLine(cx + eyeSpacing - 5, eyeY, cx + eyeSpacing + 5, eyeY, SSD1306_BLACK);
      return;
    }

    switch (exp) {
      case 0: drawEyesIdle(gfx, cx, cy, eyeSpacing, eyeY); break;
      case 1: drawEyesHappy(gfx, cx, cy, eyeSpacing, eyeY); break;
      case 2: drawEyesWorking(gfx, cx, cy, eyeSpacing, eyeY); break;
      case 3: drawEyesWorried(gfx, cx, cy, eyeSpacing, eyeY); break;
      case 4: drawEyesAngry(gfx, cx, cy, eyeSpacing, eyeY); break;
      case 5: drawEyesSleep(gfx, cx, cy, eyeSpacing, eyeY); break;
      case 6: drawEyesLove(gfx, cx, cy, eyeSpacing, eyeY); break;
      case 7: drawEyesGreeting(gfx, cx, cy, eyeSpacing, eyeY); break;
      default: drawEyesIdle(gfx, cx, cy, eyeSpacing, eyeY); break;
    }
  }

  // idle: 圆圆的大眼睛 + 高光
  static void drawEyesIdle(Adafruit_GFX* gfx, int cx, int cy, int s, int ey) {
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * s;
      // 眼眶 (椭圆)
      gfx->fillRoundRect(ex - 4, ey - 5, 9, 10, 4, SSD1306_BLACK);
      // 高光
      gfx->fillCircle(ex + 1, ey - 2, 2, SSD1306_WHITE);
      gfx->fillCircle(ex - 1, ey + 1, 1, SSD1306_WHITE);
    }
  }

  // happy: ^_^ 弯弯笑眼
  static void drawEyesHappy(Adafruit_GFX* gfx, int cx, int cy, int s, int ey) {
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * s;
      // 上弧线
      gfx->drawLine(ex - 4, ey - 3, ex, ey, SSD1306_BLACK);
      gfx->drawLine(ex + 4, ey - 3, ex, ey, SSD1306_BLACK);
      gfx->drawLine(ex - 4, ey - 3, ex - 2, ey - 4, SSD1306_BLACK);
      gfx->drawLine(ex + 4, ey - 3, ex + 2, ey - 4, SSD1306_BLACK);
      // 加粗
      gfx->drawLine(ex - 4, ey - 2, ex, ey + 1, SSD1306_BLACK);
      gfx->drawLine(ex + 4, ey - 2, ex, ey + 1, SSD1306_BLACK);
    }
  }

  // working: 认真眼 (小一点 + 眉毛)
  static void drawEyesWorking(Adafruit_GFX* gfx, int cx, int cy, int s, int ey) {
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * s;
      // 眼睛
      gfx->fillRoundRect(ex - 3, ey - 3, 7, 7, 3, SSD1306_BLACK);
      gfx->fillCircle(ex, ey - 1, 2, SSD1306_WHITE);
      // 眉毛 (略向下)
      gfx->drawLine(ex - 4, ey - 6, ex + 4, ey - 5, SSD1306_BLACK);
    }
  }

  // worried: 八字眉 + 大眼睛
  static void drawEyesWorried(Adafruit_GFX* gfx, int cx, int cy, int s, int ey) {
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * s;
      gfx->fillRoundRect(ex - 4, ey - 4, 9, 8, 4, SSD1306_BLACK);
      gfx->fillCircle(ex + 1, ey - 1, 2, SSD1306_WHITE);
      // 八字眉
      gfx->drawLine(ex - 4, ey - 5, ex, ey - 7, SSD1306_BLACK);
      gfx->drawLine(ex + 4, ey - 5, ex, ey - 7, SSD1306_BLACK);
    }
  }

  // angry: >_< 尖眼
  static void drawEyesAngry(Adafruit_GFX* gfx, int cx, int cy, int s, int ey) {
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * s;
      // 倾斜眼
      int dir = side;
      gfx->fillTriangle(ex - 3, ey - 6, ex + 4, ey - 2,
                        ex - 2, ey + 2, SSD1306_BLACK);
      gfx->fillCircle(ex, ey - 2, 1, SSD1306_WHITE);
      // 怒眉
      gfx->drawLine(ex - 3, ey - 7, ex + 4, ey - 6, SSD1306_BLACK);
      gfx->drawLine(ex - 3, ey - 8, ex + 4, ey - 7, SSD1306_BLACK);
    }
  }

  // sleep: 闭眼 + 睫毛
  static void drawEyesSleep(Adafruit_GFX* gfx, int cx, int cy, int s, int ey) {
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * s;
      // 闭眼弧线
      gfx->drawLine(ex - 4, ey, ex + 4, ey, SSD1306_BLACK);
      gfx->drawLine(ex - 3, ey - 1, ex + 3, ey - 1, SSD1306_BLACK);
      // 睫毛
      gfx->drawPixel(ex - 2, ey + 1, SSD1306_BLACK);
      gfx->drawPixel(ex + 2, ey + 1, SSD1306_BLACK);
    }
  }

  // love: ♡ 爱心眼
  static void drawEyesLove(Adafruit_GFX* gfx, int cx, int cy, int s, int ey) {
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * s;
      // 简化爱心: 两个圆 + 三角
      gfx->fillCircle(ex - 2, ey - 3, 2, SSD1306_BLACK);
      gfx->fillCircle(ex + 2, ey - 3, 2, SSD1306_BLACK);
      gfx->fillTriangle(ex - 3, ey - 2, ex + 3, ey - 2,
                        ex, ey + 2, SSD1306_BLACK);
    }
  }

  // greeting: 闪闪眼 (星形高光)
  static void drawEyesGreeting(Adafruit_GFX* gfx, int cx, int cy, int s, int ey) {
    for (int side = -1; side <= 1; side += 2) {
      int ex = cx + side * s;
      gfx->fillRoundRect(ex - 4, ey - 4, 9, 9, 4, SSD1306_BLACK);
      // 星形高光
      drawStar(gfx, ex, ey - 1, 2, SSD1306_WHITE);
    }
  }

  // ==================== 嘴巴 ====================

  static void drawMouth(Adafruit_GFX* gfx, int cx, int cy, uint8_t exp) {
    int my = cy + 8;
    switch (exp) {
      case 0: // idle: 小微笑
        gfx->drawLine(cx - 3, my, cx, my + 2, SSD1306_BLACK);
        gfx->drawLine(cx + 3, my, cx, my + 2, SSD1306_BLACK);
        break;
      case 1: // happy: 开口笑
        gfx->fillRoundRect(cx - 5, my - 2, 10, 6, 3, SSD1306_BLACK);
        gfx->fillRect(cx - 5, my - 1, 10, 3, SSD1306_WHITE);  // 牙齿
        break;
      case 2: // working: 抿嘴
        gfx->drawLine(cx - 3, my + 1, cx + 3, my + 1, SSD1306_BLACK);
        break;
      case 3: // worried: 波浪嘴
        gfx->drawLine(cx - 4, my - 1, cx - 1, my + 1, SSD1306_BLACK);
        gfx->drawLine(cx - 1, my + 1, cx + 1, my - 1, SSD1306_BLACK);
        gfx->drawLine(cx + 1, my - 1, cx + 4, my + 1, SSD1306_BLACK);
        break;
      case 4: // angry: 锯齿嘴
        gfx->drawLine(cx - 4, my, cx, my + 2, SSD1306_BLACK);
        gfx->drawLine(cx + 4, my, cx, my + 2, SSD1306_BLACK);
        gfx->drawLine(cx - 4, my - 1, cx, my + 1, SSD1306_BLACK);
        gfx->drawLine(cx + 4, my - 1, cx, my + 1, SSD1306_BLACK);
        break;
      case 5: // sleep: 张开的O嘴
        gfx->fillCircle(cx, my + 1, 3, SSD1306_BLACK);
        break;
      case 6: // love: 嘟嘴
        gfx->fillCircle(cx, my + 1, 2, SSD1306_BLACK);
        break;
      case 7: // greeting: 大笑
        gfx->fillRoundRect(cx - 6, my - 2, 12, 7, 3, SSD1306_BLACK);
        gfx->fillRect(cx - 6, my - 1, 12, 3, SSD1306_WHITE);
        break;
    }
  }

  // ==================== 腮红 ====================

  static void drawBlush(Adafruit_GFX* gfx, int cx, int cy, uint8_t exp) {
    if (exp == 1 || exp == 6 || exp == 7) {  // 开心/喜欢/欢迎
      int by = cy + 5;
      // 用点阵模拟腮红
      for (int side = -1; side <= 1; side += 2) {
        int bx = cx + side * 12;
        gfx->fillCircle(bx, by, 3, SSD1306_BLACK);
        gfx->drawPixel(bx, by, SSD1306_WHITE);  // 高光点
      }
    }
  }

  // ==================== 特效 ====================

  static void drawHeartEffect(Adafruit_GFX* gfx, int x, int y) {
    // 小爱心 (从角色头顶飘出)
    static const uint8_t heart[] = {
      0b01101100,
      0b11111110,
      0b11111110,
      0b01111100,
      0b00111000,
      0b00010000,
    };
    for (int row = 0; row < 6; row++) {
      for (int col = 0; col < 8; col++) {
        if (heart[row] & (1 << (7 - col))) {
          gfx->drawPixel(x + col - 4, y + row - 3, SSD1306_WHITE);
        }
      }
    }
  }

  static void drawSweatEffect(Adafruit_GFX* gfx, int x, int y) {
    // 大水滴
    gfx->fillCircle(x, y + 4, 3, SSD1306_WHITE);
    gfx->fillTriangle(x - 2, y - 1, x + 2, y - 1,
                      x, y + 1, SSD1306_WHITE);
  }

  static void drawZZZEffect(Adafruit_GFX* gfx, int x, int y) {
    gfx->setTextSize(1);
    gfx->setTextColor(SSD1306_WHITE);
    gfx->setCursor(x, y);
    gfx->print("Z");
    gfx->setCursor(x + 5, y - 5);
    gfx->print("z");
    gfx->setCursor(x + 10, y - 10);
    gfx->print("z");
  }

  static void drawStar(Adafruit_GFX* gfx, int cx, int cy, int r, uint16_t color) {
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
};

#endif // DEFAULT_CHIBI_H
