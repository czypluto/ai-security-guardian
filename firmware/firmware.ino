/*
 * ================================================================
 *  AI 网络安全管家 v3.0 — 精简版固件
 *  网络表情 + 状态仪表盘  双屏固定切换
 *
 *  v3.0 变更:
 *  - 移除二次元 Chibi 角色，改用大号网络表情 (颜文字)
 *  - 双屏: 表情屏 (emoji + 状态) / 仪表盘 (安全详情)
 *  - 按键或 PC 端指令切换，不再自动轮播
 *  - 离线状态明确标识 "DISCONNECTED"，不再用睡眠表情
 *  - 精简动画系统，保持 30fps 基础眨眼 + 呼吸
 * ================================================================
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>

// ==================== 配置 ====================
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
// I2C 地址 (ESP32 OLED 常见 0x3C 或 0x3D)
#define OLED_ADDR_1 0x3C
#define OLED_ADDR_2 0x3D
#define SDA_PIN 21
#define SCL_PIN 22
#define BUZZER_PIN 5
#define LED_PIN 4
#define BUTTON_PIN 0        // BOOT 键: 切换屏幕
#define SERIAL_BAUD 115200

// ==================== 屏幕定义 ====================
#define SCREEN_EMOJI   0
#define SCREEN_STATUS  1
#define SCREEN_COUNT   2

// ==================== 表情枚举 ====================
#define EXP_IDLE      0   // ･ω･  待机
#define EXP_HAPPY     1   // ^o^   开心/安全
#define EXP_WORKING   2   // ･_･  工作中
#define EXP_WORRIED   3   // ;_;   担忧/警告
#define EXP_ANGRY     4   // >_<   危险!
#define EXP_OFFLINE   5   // ⚡    断连
#define EXP_GREETING  7   // ★o★  欢迎 (6=EXP_LOVE 已废弃)

// ==================== 全局对象 ====================
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
bool displayOK = false;

// ==================== 系统状态 ====================
struct SystemState {
  // AI
  String ai_status = "idle";
  // 安全
  String sec_level = "safe";
  int threat_count = 0;
  int blocked_count = 0;
  // 网络
  int active_connections = 0;
  int suspicious_ips = 0;
  // 系统
  bool firewall_on = true;
  bool defender_on = true;
  float cpu_usage = 0;
  float mem_usage = 0;
  long uptime = 0;
  // 表情
  uint8_t expression = EXP_GREETING;
} sys;

// ==================== 动画状态 (精简) ====================
struct AnimState {
  // 眨眼 (仅表情屏)
  bool blinking = false;
  uint8_t blinkFrame = 0;
  unsigned long lastBlink = 0;
  unsigned long blinkInterval = 3000;
  // 呼吸偏移
  int breathOffset = 0;
  // 帧计时
  unsigned long frameTimer = 0;
} anim;

// ==================== 屏幕 + 连接 ====================
uint8_t currentScreen = SCREEN_EMOJI;
unsigned long lastDataReceived = 0;
bool dataTimeout = false;
bool buttonPressed = false;

// ==================== 初始化 ====================
void setup() {
  Serial.begin(SERIAL_BAUD);

  // 初始化 I2C 并扫描设备
  Wire.begin(SDA_PIN, SCL_PIN);
  Serial.println(F("{\"status\":\"booting\",\"msg\":\"I2C scanning...\"}"));

  // 扫描 I2C 总线
  int found = 0;
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.print(F("{\"i2c\":\"0x"));
      Serial.print(addr, HEX);
      Serial.println(F("\"}"));
      found++;
    }
  }

  // 尝试初始化 OLED (双地址自动适配)
  if (display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR_1)) {
    displayOK = true;
    Serial.println(F("{\"oled\":\"0x3C OK\"}"));
  } else if (display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR_2)) {
    displayOK = true;
    Serial.println(F("{\"oled\":\"0x3D OK\"}"));
  } else {
    Serial.println(F("{\"oled\":\"FAIL\",\"found\":"));
    Serial.print(found);
    Serial.println(F("}"));
  }

  if (displayOK) {
    // 强制亮屏 + 高对比度
    display.ssd1306_command(SSD1306_DISPLAYON);
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(0xFF);  // 最大对比度
    display.clearDisplay();
    display.display();
    delay(100);
    // 填充全白测试
    display.fillScreen(SSD1306_WHITE);
    display.display();
    delay(300);
    display.clearDisplay();
    display.display();
  }

  if (BUZZER_PIN >= 0) pinMode(BUZZER_PIN, OUTPUT);
  if (LED_PIN >= 0) pinMode(LED_PIN, OUTPUT);
  if (BUTTON_PIN >= 0) pinMode(BUTTON_PIN, INPUT_PULLUP);

  // 启动画面
  if (displayOK) showBootScreen();

  sys.expression = EXP_GREETING;
  lastDataReceived = millis();
  anim.lastBlink = millis();
  anim.blinkInterval = random(2000, 5000);
  anim.frameTimer = millis();

  Serial.print(F("{\"status\":\"ready\",\"device\":\"ai-guardian-v3\",\"version\":\"3.0\",\"oled\":"));
  Serial.print(displayOK ? "true" : "false");
  Serial.println(F("}"));
  beep(1);
}

void showBootScreen() {
  if (!displayOK) return;
  display.clearDisplay();
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(16, 8);
  display.println(F("AI Guard"));
  display.setTextSize(1);
  display.setCursor(28, 32);
  display.println(F("v3.0 Emoji"));
  // 进度条
  for (int i = 0; i <= 100; i += 8) {
    display.fillRect(14, 48, i, 5, SSD1306_WHITE);
    display.display();
    delay(25);
  }
  delay(400);
  display.clearDisplay();
  display.display();
}

// ==================== 主循环 ====================
void loop() {
  unsigned long now = millis();

  handleSerial();

  // ---- 按键: 切换屏幕 ----
  if (BUTTON_PIN >= 0 && digitalRead(BUTTON_PIN) == LOW && !buttonPressed) {
    buttonPressed = true;
    currentScreen = (currentScreen + 1) % SCREEN_COUNT;
  }
  if (BUTTON_PIN >= 0 && digitalRead(BUTTON_PIN) == HIGH) {
    buttonPressed = false;
  }

  // ---- 数据超时检测 (30秒) ----
  if (now - lastDataReceived > 30000) {
    if (!dataTimeout) {
      dataTimeout = true;
      sys.ai_status = "offline";
    }
  } else {
    dataTimeout = false;
  }

  // ---- 帧更新 (30fps) ----
  if (now - anim.frameTimer > 33) {
    updateAnimation(now);
    anim.frameTimer = now;
  }

  // ---- 渲染 ----
  render(now);

  // ---- 告警 ----
  updateAlerts();

  delay(20);
}

// ==================== 动画更新 (精简) ====================
void updateAnimation(unsigned long now) {
  // 眨眼
  if (anim.blinking) {
    anim.blinkFrame++;
    if (anim.blinkFrame >= 3) {
      anim.blinkFrame = 0;
      anim.blinking = false;
      anim.blinkInterval = random(2000, 5000);
      anim.lastBlink = now;
    }
  } else if (now - anim.lastBlink > anim.blinkInterval) {
    anim.blinking = true;
    anim.blinkFrame = 0;
  }

  // 呼吸 (正弦)
  float phase = (now % 3200) / 3200.0 * 2 * PI;
  anim.breathOffset = (int)(sin(phase) * 1.0);
}

// ==================== 渲染 ====================
void render(unsigned long now) {
  if (!displayOK) return;
  display.clearDisplay();

  // 顶部状态条
  drawTopBar(now);

  switch (currentScreen) {
    case SCREEN_EMOJI:  drawEmojiScreen(now);  break;
    case SCREEN_STATUS: drawStatusScreen();     break;
  }

  display.display();
}

// ==================== 顶部状态条 ====================
void drawTopBar(unsigned long now) {
  // 连接指示
  if (dataTimeout) {
    // 断连: 闪烁 "!"
    if ((now / 500) % 2) {
      display.fillRect(0, 0, 8, 7, SSD1306_WHITE);
      display.setTextColor(SSD1306_BLACK);
      display.setCursor(1, 0);
      display.print("!");
      display.setTextColor(SSD1306_WHITE);
    }
  } else {
    // 连接正常: 信号条
    for (int i = 0; i < 4; i++)
      display.fillRect(i * 3, 7 - i * 2, 2, 2 + i * 2, SSD1306_WHITE);
  }

  // 安全指示灯 (右侧)
  uint16_t ledColor = SSD1306_WHITE;
  if (sys.sec_level == "danger")
    ledColor = (now / 300) % 2 ? SSD1306_WHITE : SSD1306_BLACK;
  else if (sys.sec_level == "warning")
    ledColor = (now / 600) % 2 ? SSD1306_WHITE : SSD1306_BLACK;
  display.fillCircle(121, 4, 3, ledColor);

  // 分隔线
  display.drawLine(0, 8, 127, 8, SSD1306_WHITE);
}

// ==================== 屏幕0: 表情屏 ====================
void drawEmojiScreen(unsigned long now) {
  int ey = 18 + anim.breathOffset;  // 轻微呼吸浮动

  // ---- 大号 emoji ----
  display.setTextSize(3);
  display.setTextColor(SSD1306_WHITE);

  // blinkFrame=0 -> 正常眼, blinkFrame=1 -> 半闭, blinkFrame=2 -> 全闭
  const char* emoji;
  bool eyesClosed = (anim.blinkFrame == 2);

  if (dataTimeout) {
    emoji = "!!";   // 断连告警
  } else {
    switch (sys.expression) {
      case EXP_IDLE:     emoji = eyesClosed ? "- -" : "o o";   break;
      case EXP_HAPPY:    emoji = eyesClosed ? "- -" : "^ ^";   break;
      case EXP_WORKING:  emoji = eyesClosed ? "- -" : ". .";   break;
      case EXP_WORRIED:  emoji = "; ;";                        break;
      case EXP_ANGRY:    emoji = "> <";                        break;
      case EXP_OFFLINE:  emoji = "x x";                        break;
      case EXP_GREETING: emoji = eyesClosed ? "- -" : "O O";   break;
      default:           emoji = "o o";                        break;
    }
  }

  // 居中显示 emoji
  int tw = strlen(emoji) * 18;  // size 3, 每个字符约 18px
  display.setCursor((128 - tw) / 2, ey);
  display.print(emoji);

  // 嘴巴 (在眼睛下方)
  display.setTextSize(2);
  const char* mouth;
  if (dataTimeout) {
    mouth = "___";
  } else {
    switch (sys.expression) {
      case EXP_IDLE:     mouth = "w";    break;
      case EXP_HAPPY:    mouth = "v";    break;
      case EXP_WORKING:  mouth = "_";    break;
      case EXP_WORRIED:  mouth = "_";    break;
      case EXP_ANGRY:    mouth = "_";    break;
      case EXP_OFFLINE:  mouth = "_";    break;
      case EXP_GREETING: mouth = "v";    break;
      default:           mouth = "w";    break;
    }
  }
  int mw = strlen(mouth) * 12;
  display.setCursor((128 - mw) / 2, ey + 24);
  display.print(mouth);

  // ---- 状态文字 ----
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  int sy = 52;
  if (dataTimeout) {
    display.setCursor(28, sy);
    display.print(F("-- DISCONNECTED --"));
  } else if (sys.sec_level == "danger") {
    display.setCursor(16, sy);
    display.print(F("!! DANGER !!"));
  } else if (sys.sec_level == "warning") {
    display.setCursor(22, sy);
    display.print(F("... WARNING ..."));
  } else if (sys.ai_status == "working") {
    display.setCursor(28, sy);
    display.print(F("Guarding..."));
  } else {
    display.setCursor(40, sy);
    display.print(F("Secure"));
  }
}

// ==================== 屏幕1: 状态仪表盘 ====================
void drawStatusScreen() {
  int y = 12;

  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  // ---- 安全等级 ----
  display.setCursor(2, y);
  display.print(F("Security: "));
  if (sys.sec_level == "danger") {
    display.print(F("DANGER"));
  } else if (sys.sec_level == "warning") {
    display.print(F("WARNING"));
  } else {
    display.print(F("SAFE"));
  }
  y += 12;

  // ---- 防火墙 / Defender ----
  display.setCursor(2, y);
  display.print(F("FW:"));
  display.print(sys.firewall_on ? "ON " : "OFF");
  display.print(F("  AV:"));
  display.print(sys.defender_on ? "ON" : "OFF");
  y += 12;

  // ---- 威胁 ----
  display.setCursor(2, y);
  display.print(F("Threats: "));
  display.print(sys.threat_count);
  display.print(F("  Blocked: "));
  display.print(sys.blocked_count);
  y += 12;

  // ---- 网络 ----
  display.setCursor(2, y);
  display.print(F("Conns: "));
  display.print(sys.active_connections);
  display.print(F("  SusIP: "));
  display.print(sys.suspicious_ips);
  y += 12;

  // ---- CPU / MEM ----
  display.setCursor(2, y);
  display.print(F("CPU:"));
  display.print((int)sys.cpu_usage);
  display.print(F("%  MEM:"));
  display.print((int)sys.mem_usage);
  display.print(F("%"));
}

// ==================== 表情映射 (不再包含 SLEEP) ====================
uint8_t mapStatusToExpression() {
  if (dataTimeout)              return EXP_OFFLINE;
  if (sys.sec_level == "danger")  return EXP_ANGRY;
  if (sys.sec_level == "warning") return EXP_WORRIED;
  if (sys.ai_status == "working") return EXP_WORKING;
  if (sys.ai_status == "alert")   return EXP_WORRIED;
  // 安全 + 无威胁 → 开心
  if (sys.threat_count == 0 && sys.sec_level == "safe")
    return EXP_HAPPY;
  return EXP_IDLE;
}

// ==================== Serial 通信 ====================
void handleSerial() {
  static String buf = "";
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      processCommand(buf);
      buf = "";
    } else {
      buf += c;
    }
  }
}

void processCommand(String json) {
  json.trim();
  if (json.length() == 0) return;

  StaticJsonDocument<1024> doc;
  if (deserializeJson(doc, json)) {
    Serial.println(F("{\"error\":\"parse\"}"));
    return;
  }

  String cmd = doc["cmd"] | "";

  if (cmd == "update") {
    sys.ai_status    = doc["ai_status"]    | sys.ai_status;
    sys.sec_level    = doc["sec_level"]    | sys.sec_level;
    sys.threat_count   = doc["threat_count"]   | sys.threat_count;
    sys.blocked_count  = doc["blocked_count"]  | sys.blocked_count;
    sys.active_connections = doc["active_connections"] | sys.active_connections;
    sys.suspicious_ips     = doc["suspicious_ips"]     | sys.suspicious_ips;
    sys.firewall_on   = doc["firewall_on"]   | sys.firewall_on;
    sys.defender_on   = doc["defender_on"]   | sys.defender_on;
    sys.cpu_usage     = doc["cpu_usage"]     | sys.cpu_usage;
    sys.mem_usage     = doc["mem_usage"]     | sys.mem_usage;
    sys.uptime        = doc["uptime"]        | sys.uptime;

    sys.expression = mapStatusToExpression();
    lastDataReceived = millis();
    Serial.println(F("{\"status\":\"ok\"}"));

  } else if (cmd == "ping") {
    lastDataReceived = millis();
    Serial.println(F("{\"status\":\"pong\"}"));

  } else if (cmd == "alert") {
    sys.sec_level = "danger";
    sys.expression = EXP_ANGRY;
    currentScreen = SCREEN_EMOJI;  // 告警时切回表情屏
    beep(5);
    Serial.println(F("{\"status\":\"alert_ack\"}"));

  } else if (cmd == "expression") {
    int exp = doc["expression"] | -1;
    if (exp >= 0 && exp < 8) {
      sys.expression = exp;
    }
    Serial.println(F("{\"status\":\"ok\"}"));

  } else if (cmd == "say") {
    // v3.0 使用表情变化来表达，不再需要气泡
    String text = doc["text"] | "";
    if (text.length() > 0) {
      // 短暂切到表情屏显示状态变化
      currentScreen = SCREEN_EMOJI;
    }
    Serial.println(F("{\"status\":\"ok\"}"));

  } else if (cmd == "screen") {
    int sc = doc["screen"] | 0;
    if (sc >= 0 && sc < SCREEN_COUNT) {
      currentScreen = sc;
    }
    Serial.println(F("{\"status\":\"ok\"}"));

  } else if (cmd == "reboot") {
    Serial.println(F("{\"status\":\"rebooting\"}"));
    delay(100);
    ESP.restart();

  } else {
    Serial.println(F("{\"error\":\"unknown_command\"}"));
  }
}

// ==================== 告警 ====================
void updateAlerts() {
  if (BUZZER_PIN >= 0) {
    if (sys.sec_level == "danger")
      digitalWrite(BUZZER_PIN, (millis() / 200) % 2);
    else if (sys.sec_level == "warning")
      digitalWrite(BUZZER_PIN, (millis() / 800) % 2);
    else
      digitalWrite(BUZZER_PIN, LOW);
  }
  if (LED_PIN >= 0) {
    if (sys.sec_level == "danger")      analogWrite(LED_PIN, 255);
    else if (sys.sec_level == "warning") analogWrite(LED_PIN, 80);
    else                                 analogWrite(LED_PIN, 0);
  }
}

void beep(int times) {
  if (BUZZER_PIN < 0) return;
  for (int i = 0; i < times; i++) {
    digitalWrite(BUZZER_PIN, HIGH); delay(80);
    digitalWrite(BUZZER_PIN, LOW);  delay(60);
  }
}
