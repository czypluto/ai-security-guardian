/*
 * ================================================================
 *  二次元角色动画引擎 - Character Animation Engine
 *  Supports: OLED 128x64 monochrome / T-Display color TFT
 * ================================================================
 *
 *  表情系统:
 *    idle    - 普通脸 (眨眼睛)
 *    happy   - 开心 (^_^)
 *    working - 认真 (专注眼 + 汗滴)
 *    worried - 担心 (八字眉)
 *    angry   - 生气 (>_<)
 *    sleep   - 睡觉 (Zzz)
 *    love    - 喜欢 (♡眼)
 *    greeting- 欢迎 (闪闪眼 + 挥手)
 *
 *  动画:
 *    blink   - 眨眼 (周期性)
 *    bounce  - 弹跳 (收到消息)
 *    shake   - 发抖 (警告时)
 *    sweat   - 汗滴 (CPU高)
 */

#ifndef CHARACTER_ENGINE_H
#define CHARACTER_ENGINE_H

#include <Arduino.h>

// ==================== 角色数据结构 ====================

// OLED 角色定义 (单色位图)
#define CHAR_WIDTH  40    // 角色宽度 (像素)
#define CHAR_HEIGHT 48    // 角色高度
#define CHAR_BYTES  ((CHAR_WIDTH * CHAR_HEIGHT) / 8)  // 240 bytes

// 表情枚举
enum Expression {
  EXP_IDLE = 0,
  EXP_HAPPY,
  EXP_WORKING,
  EXP_WORRIED,
  EXP_ANGRY,
  EXP_SLEEP,
  EXP_LOVE,
  EXP_GREETING,
  EXP_COUNT
};

// 每个角色存储所有表情的位图
struct CharacterData {
  const char* name;              // 角色名字
  const uint8_t* frames[EXP_COUNT];  // 表情帧数组 (PROGMEM)
  uint8_t width;
  uint8_t height;
};

// 动画状态
struct AnimationState {
  Expression currentExp = EXP_IDLE;
  Expression targetExp = EXP_IDLE;

  // 眨眼系统
  bool isBlinking = false;
  uint8_t blinkFrame = 0;       // 0=睁开, 1=半闭, 2=全闭
  unsigned long lastBlink = 0;
  unsigned long nextBlinkInterval = 3000;  // 随机眨眼间隔

  // 弹跳系统
  int bounceOffset = 0;         // 垂直偏移
  int bounceVelocity = 0;
  unsigned long bounceStart = 0;
  bool isBouncing = false;

  // 抖动系统
  int shakeOffset = 0;
  unsigned long shakeStart = 0;
  bool isShaking = false;

  // 汗滴
  bool showSweatDrop = false;

  // 爱心
  int heartAlpha = 0;           // 0-8, 爱心显示强度
  unsigned long heartTimer = 0;

  // Zzz (睡觉)
  int zzzOffset = 0;
  unsigned long zzzTimer = 0;

  // 挥手
  int wavePhase = 0;
  unsigned long waveTimer = 0;

  // 通用
  unsigned long animTimer = 0;
};

// ==================== 角色引擎类 ====================

class CharacterEngine {
private:
  CharacterData* _char;
  AnimationState _anim;
  unsigned long _lastFrame;
  bool _colorMode;
  int _screenW, _screenH;

public:
  CharacterEngine() {
    _char = nullptr;
    _lastFrame = 0;
    _colorMode = false;
  }

  // 加载角色
  void loadCharacter(CharacterData* ch) {
    _char = ch;
    _anim = AnimationState();  // 重置动画
    _anim.currentExp = EXP_GREETING;
    _anim.targetExp = EXP_IDLE;
    _anim.lastBlink = millis();
    _anim.animTimer = millis();
  }

  // 设置目标表情
  void setExpression(Expression exp) {
    if (_anim.targetExp != exp) {
      _anim.targetExp = exp;
      if (exp == EXP_HAPPY || exp == EXP_LOVE) {
        triggerBounce();
      }
      if (exp == EXP_WORRIED || exp == EXP_ANGRY) {
        triggerShake();
      }
    }
  }

  // 触发弹跳 (开心反应)
  void triggerBounce() {
    _anim.isBouncing = true;
    _anim.bounceVelocity = -4;
    _anim.bounceOffset = 0;
    _anim.bounceStart = millis();
  }

  // 触发抖动 (警告反应)
  void triggerShake() {
    _anim.isShaking = true;
    _anim.shakeStart = millis();
  }

  // 触发爱心
  void triggerHeart() {
    _anim.heartAlpha = 8;
    _anim.heartTimer = millis();
  }

  // 触发汗滴
  void setSweatDrop(bool show) {
    _anim.showSweatDrop = show;
  }

  // 主更新循环 (每帧调用)
  void update() {
    unsigned long now = millis();
    if (now - _anim.animTimer < 33) return;  // 30fps
    _anim.animTimer = now;

    // 眨眼逻辑
    updateBlink(now);

    // 弹跳物理
    if (_anim.isBouncing) {
      _anim.bounceOffset += _anim.bounceVelocity;
      _anim.bounceVelocity += 1;  // 重力
      if (_anim.bounceOffset >= 0) {
        _anim.bounceOffset = 0;
        _anim.bounceVelocity = 0;
        _anim.isBouncing = false;
      }
    }

    // 抖动
    if (_anim.isShaking) {
      _anim.shakeOffset = (sin(now * 0.03) * 3);
      if (now - _anim.shakeStart > 600) {
        _anim.shakeOffset = 0;
        _anim.isShaking = false;
      }
    }

    // 爱心衰减
    if (_anim.heartAlpha > 0 && now - _anim.heartTimer > 400) {
      _anim.heartAlpha--;
      _anim.heartTimer = now;
    }

    // Zzz 上浮
    if (_anim.currentExp == EXP_SLEEP || _anim.targetExp == EXP_SLEEP) {
      if (now - _anim.zzzTimer > 600) {
        _anim.zzzOffset = (_anim.zzzOffset + 1) % 4;
        _anim.zzzTimer = now;
      }
    }

    // 挥手
    if (now - _anim.waveTimer > 150) {
      _anim.wavePhase = (_anim.wavePhase + 1) % 4;
      _anim.waveTimer = now;
    }

    // 平滑过渡到目标表情
    if (_anim.currentExp != _anim.targetExp && !_anim.isBlinking) {
      // 简单切换 (带 blink 过渡)
      if (_anim.blinkFrame == 2) {
        _anim.currentExp = _anim.targetExp;
      }
    }
  }

  // 眨眼更新
  void updateBlink(unsigned long now) {
    if (_anim.isBlinking) {
      _anim.blinkFrame++;
      if (_anim.blinkFrame >= 3) {
        _anim.blinkFrame = 0;
        _anim.isBlinking = false;
        _anim.nextBlinkInterval = random(2000, 6000);
        _anim.lastBlink = now;
      }
    } else if (now - _anim.lastBlink > _anim.nextBlinkInterval) {
      _anim.isBlinking = true;
      _anim.blinkFrame = 0;
    }
  }

  // ==================== OLED 渲染 ====================

  // 在 OLED 上绘制角色 (位置 x, y)
  void drawOLED(Adafruit_SSD1306* display, int x, int y) {
    if (!_char) return;

    int drawX = x + _anim.shakeOffset;
    int drawY = y + _anim.bounceOffset;

    Expression exp = (_anim.isBlinking && _anim.blinkFrame == 2)
                     ? EXP_SLEEP  // 闭眼帧
                     : _anim.currentExp;

    // 绘制角色本体
    const uint8_t* frame = _char->frames[exp];
    if (frame) {
      drawBitmap(display, drawX, drawY, _char->width, _char->height, frame);
    }

    // 汗滴 (表情上方)
    if (_anim.showSweatDrop) {
      drawSweatDrop(display, drawX + _char->width - 6, drawY - 4);
    }

    // 爱心
    if (_anim.heartAlpha > 0) {
      drawHeart(display, drawX + _char->width + 4, drawY - 2, _anim.heartAlpha);
    }

    // Zzz
    if (exp == EXP_SLEEP || _anim.currentExp == EXP_SLEEP) {
      drawZZZ(display, drawX + _char->width + 2, drawY - 4 - _anim.zzzOffset * 2);
    }

    // 挥手效果 (GREETING 时)
    if (_anim.currentExp == EXP_GREETING || exp == EXP_GREETING) {
      drawWaveHand(display, drawX + _char->width - 4, drawY + 8, _anim.wavePhase);
    }
  }

  // ==================== 对话气泡 ====================

  // 在角色上方绘制对话气泡
  void drawSpeechBubble(Adafruit_SSD1306* display, int charX, int charY,
                         const String& text, int maxWidth = 80) {
    // 气泡位置 (角色右上方)
    int bx = charX + 20;
    int by = charY - 20;

    // 文字换行计算
    int textW = text.length() * 6;  // 6px per char (size 1)
    int bw = min(textW + 10, maxWidth);
    int bh = 12;

    // 气泡背景
    display->fillRoundRect(bx - 2, by - 2, bw + 4, bh + 4, 2, SSD1306_WHITE);
    // 气泡尾巴
    display->fillTriangle(bx + 4, by + bh + 2,
                          bx + 8, by + bh + 2,
                          bx + 6, by + bh + 6, SSD1306_WHITE);

    // 文字
    display->setTextSize(1);
    display->setTextColor(SSD1306_BLACK);
    display->setCursor(bx + 2, by + 2);
    display->print(text);
    display->setTextColor(SSD1306_WHITE);
  }

private:
  // 绘制单色位图
  void drawBitmap(Adafruit_SSD1306* display, int x, int y,
                  int w, int h, const uint8_t* bitmap) {
    for (int row = 0; row < h; row++) {
      for (int col = 0; col < w; col++) {
        int byteIdx = (row * w + col) / 8;
        int bitIdx = 7 - ((row * w + col) % 8);
        if (pgm_read_byte(&bitmap[byteIdx]) & (1 << bitIdx)) {
          display->drawPixel(x + col, y + row, SSD1306_WHITE);
        }
      }
    }
  }

  void drawSweatDrop(Adafruit_SSD1306* display, int x, int y) {
    display->fillCircle(x, y + 2, 2, SSD1306_WHITE);
    display->drawPixel(x, y, SSD1306_WHITE);
  }

  void drawHeart(Adafruit_SSD1306* display, int x, int y, int alpha) {
    if (alpha <= 0) return;
    // 小型爱心 8x8
    const uint8_t heartBitmap[] = {
      0b00110110,
      0b01111111,
      0b01111111,
      0b00111110,
      0b00011100,
      0b00001000,
    };
    for (int row = 0; row < 6; row++) {
      for (int col = 0; col < 8; col++) {
        if ((heartBitmap[row] >> (7 - col)) & 1) {
          if (alpha > 4 || (millis() / 200) % 2) {
            display->drawPixel(x + col, y + row, SSD1306_WHITE);
          }
        }
      }
    }
  }

  void drawZZZ(Adafruit_SSD1306* display, int x, int y) {
    display->setTextSize(1);
    display->setCursor(x, y);
    display->print("Z");
    display->setCursor(x + 4, y - 4);
    display->print("z");
    display->setCursor(x + 8, y - 8);
    display->print("z");
  }

  void drawWaveHand(Adafruit_SSD1306* display, int x, int y, int phase) {
    // 简单的小弧线表示挥手
    int offset = phase < 2 ? phase * 2 : (3 - phase) * 2;
    for (int i = 0; i < 3; i++) {
      display->drawPixel(x + i, y - offset - i, SSD1306_WHITE);
    }
  }

public:
  // ==================== TFT 彩色渲染 (T-Display) ====================
  // (TFT版本使用完整色彩，这里提供接口)

  void drawTFT(TFT_eSPI* tft, int x, int y) {
    // 彩色版本 - 支持 16bit RGB565 位图
    // 此处使用 OLED 兼容的简化渲染，TFT 版本见 character_engine_tft.h
    // TFT 版本支持:
    //  - 肤色填充
    //  - 发色渐变
    //  - 瞳色变化
    //  - 背景特效
  }
};

#endif // CHARACTER_ENGINE_H
