/*
 * ================================================================
 *  AI 网络安全管家 v2.0 - 陪伴版固件
 *  二次元角色 "安小盾" + 安全管家 一体固件
 *
 *  新增功能:
 *  - 🎭 二次元 Chibi 角色实时互动
 *  - 💬 对话气泡 + 情感反馈
 *  - 🎬 8种表情 (idle/happy/working/worried/angry/sleep/love/greeting)
 *  - ✨ 爱心/汗滴/Zzz/挥手 动画特效
 *  - 🔄 3屏轮播 (角色屏 / 安全屏 / 网络屏)
 *  - 📥 支持导入自定义角色位图
 * ================================================================
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include "characters/default_chibi.h"

// ==================== 配置 ====================
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_ADDR 0x3C
#define SDA_PIN 21
#define SCL_PIN 22
#define BUZZER_PIN 5
#define LED_PIN 4
#define BUTTON_PIN 0       // 手动切换屏幕按键 (ESP32 BOOT键)

#define WIFI_SSID "YOUR_WIFI"
#define WIFI_PASS "YOUR_PASS"
#define WIFI_ENABLED false
#define SERIAL_BAUD 115200

// ==================== 常量 ====================
#define SCREEN_CHARACTER  0
#define SCREEN_SECURITY   1
#define SCREEN_NETWORK    2
#define SCREEN_COUNT      3
#define AUTO_SWITCH_MS    5000

// 表情映射
#define EXP_IDLE      0
#define EXP_HAPPY     1
#define EXP_WORKING   2
#define EXP_WORRIED   3
#define EXP_ANGRY     4
#define EXP_SLEEP     5
#define EXP_LOVE      6
#define EXP_GREETING  7

// ==================== 全局对象 ====================
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
WiFiServer wifiServer(8080);
WiFiClient wifiClient;

// ==================== 状态数据 ====================
struct SystemState {
  // AI 状态
  String ai_status = "idle";       // idle | working | alert | offline
  String ai_task = "";
  int ai_progress = 0;

  // 安全状态
  String sec_level = "safe";       // safe | warning | danger
  int threat_count = 0;
  int blocked_count = 0;
  String last_threat = "";

  // 网络
  int active_connections = 0;
  int suspicious_ips = 0;
  String net_status = "normal";

  // 系统
  bool firewall_on = true;
  bool defender_on = true;
  float cpu_usage = 0;
  float mem_usage = 0;
  long uptime = 0;

  // 消息
  String messages[5];
  int msg_count = 0;

  // 角色相关
  uint8_t char_expression = EXP_IDLE;
  String char_custom_msg = "";
  bool char_custom = false;       // 是否使用自定义角色
} sys;

// ==================== 动画状态 ====================
struct AnimState {
  // 眨眼
  bool blinking = false;
  uint8_t blinkFrame = 0;      // 0=睁眼, 1=半闭, 2=全闭
  unsigned long lastBlink = 0;
  unsigned long blinkInterval = 3000;

  // 弹跳
  int bounceY = 0;
  int bounceV = 0;
  bool bouncing = false;

  // 抖动
  int shakeX = 0;
  unsigned long shakeEnd = 0;

  // 特效
  bool showHeart = false;
  unsigned long heartEnd = 0;
  bool showSweat = false;
  int zzzOffset = 0;
  int wavePhase = 0;

  // 消息气泡
  String bubbleText = "";
  unsigned long bubbleEnd = 0;

  unsigned long frameTimer = 0;
  unsigned long animTimer = 0;
} anim;

// 屏幕控制
uint8_t currentScreen = SCREEN_CHARACTER;
unsigned long lastScreenSwitch = 0;
unsigned long lastDataReceived = 0;
bool dataTimeout = false;
bool buttonPressed = false;

// ==================== 初始化 ====================
void setup() {
  Serial.begin(SERIAL_BAUD);

  // OLED
  Wire.begin(SDA_PIN, SCL_PIN);
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("OLED failed"));
  }
  display.clearDisplay();
  display.display();

  // 外设
  if (BUZZER_PIN >= 0) pinMode(BUZZER_PIN, OUTPUT);
  if (LED_PIN >= 0) pinMode(LED_PIN, OUTPUT);
  if (BUTTON_PIN >= 0) pinMode(BUTTON_PIN, INPUT_PULLUP);

  // 启动动画
  showStartupAnimation();

  // WiFi
  if (WIFI_ENABLED) {
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int t = 0;
    while (WiFi.status() != WL_CONNECTED && t++ < 20) delay(500);
    if (WiFi.status() == WL_CONNECTED) wifiServer.begin();
  }

  // 初始状态
  sys.char_expression = EXP_GREETING;
  sayBubble("你好! 我是安小盾~");
  lastDataReceived = millis();
  lastScreenSwitch = millis();
  anim.lastBlink = millis();
  anim.blinkInterval = random(2000, 5000);
  anim.frameTimer = millis();
  anim.animTimer = millis();

  Serial.println(F("{\"status\":\"ready\",\"device\":\"ai-guardian-v2\",\"character\":\"an-chan\"}"));
  beep(1);
}

// ==================== 启动动画 ====================
void showStartupAnimation() {
  display.clearDisplay();
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(8, 5);
  display.println(F("AI Guard"));
  display.setTextSize(1);
  display.setCursor(20, 28);
  display.println(F("v2.0 陪伴版"));

  // 进度条
  for (int i = 0; i <= 100; i += 5) {
    display.fillRect(14, 45, i, 6, SSD1306_WHITE);
    display.display();
    delay(30);
  }
  delay(800);

  // 角色登场
  display.clearDisplay();
  DefaultChibi::draw(&display, 5, 8, EXP_GREETING);
  display.display();
  delay(1500);
  display.clearDisplay();
  display.display();
}

// ==================== 主循环 ====================
void loop() {
  unsigned long now = millis();

  handleSerial();
  if (WIFI_ENABLED) handleWiFi();

  // 按键检测
  if (BUTTON_PIN >= 0 && digitalRead(BUTTON_PIN) == LOW && !buttonPressed) {
    buttonPressed = true;
    currentScreen = (currentScreen + 1) % SCREEN_COUNT;
    lastScreenSwitch = now;
  }
  if (BUTTON_PIN >= 0 && digitalRead(BUTTON_PIN) == HIGH) {
    buttonPressed = false;
  }

  // 自动切屏
  if (now - lastScreenSwitch > AUTO_SWITCH_MS) {
    currentScreen = (currentScreen + 1) % SCREEN_COUNT;
    lastScreenSwitch = now;
  }

  // 数据超时检测
  if (now - lastDataReceived > 10000) {
    if (!dataTimeout) {
      dataTimeout = true;
      sys.ai_status = "offline";
      sys.char_expression = EXP_WORRIED;
      sayBubble("主人? 还在吗...");
    }
  } else {
    dataTimeout = false;
  }

  // 帧更新 (30fps)
  if (now - anim.frameTimer > 33) {
    updateAnimation(now);
    anim.frameTimer = now;
  }

  // 渲染
  render(now);

  // 告警
  updateAlerts();

  delay(20);
}

// ==================== 动画更新 ====================
void updateAnimation(unsigned long now) {
  if (now - anim.animTimer < 100) return;
  anim.animTimer = now;

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

  // 弹跳物理
  if (anim.bouncing) {
    anim.bounceY += anim.bounceV;
    anim.bounceV += 1;
    if (anim.bounceY >= 0) {
      anim.bounceY = 0;
      anim.bounceV = 0;
      anim.bouncing = false;
    }
  }

  // 抖动衰减
  if (anim.shakeX != 0 && now > anim.shakeEnd) {
    anim.shakeX = 0;
  } else if (anim.shakeX != 0) {
    anim.shakeX = sin(now * 0.04) * 2;
  }

  // 爱心衰减
  if (anim.showHeart && now > anim.heartEnd) {
    anim.showHeart = false;
  }

  // Zzz 浮动
  if (sys.char_expression == EXP_SLEEP) {
    anim.zzzOffset = (anim.zzzOffset + 1) % 4;
  }

  // 挥手
  anim.wavePhase = (anim.wavePhase + 1) % 4;

  // 气泡过期
  if (anim.bubbleText.length() > 0 && now > anim.bubbleEnd) {
    anim.bubbleText = "";
  }
}

// ==================== 渲染 ====================
void render(unsigned long now) {
  display.clearDisplay();

  // 顶部状态条
  drawTopBar();

  switch (currentScreen) {
    case SCREEN_CHARACTER: drawCharacterScreen(); break;
    case SCREEN_SECURITY:  drawSecurityScreen(); break;
    case SCREEN_NETWORK:   drawNetworkScreen(); break;
  }

  display.display();
}

// ==================== 顶部状态条 ====================
void drawTopBar() {
  // 信号条
  if (dataTimeout) {
    display.fillRect(0, 0, 6, 8, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
    display.setCursor(0, 0);
    display.print("!");
    display.setTextColor(SSD1306_WHITE);
  } else {
    for (int i = 0; i < 4; i++)
      display.fillRect(i * 3, 7 - i * 2, 2, 2 + i * 2, SSD1306_WHITE);
  }

  // 安全指示灯
  uint16_t ledColor = SSD1306_WHITE;
  if (sys.sec_level == "danger")
    ledColor = (now_ish() / 300) % 2 ? SSD1306_WHITE : SSD1306_BLACK;
  display.fillCircle(121, 4, 3, ledColor);

  // 分隔线
  display.drawLine(0, 8, 128, 8, SSD1306_WHITE);
}

// 辅助 (避免 millis() 在 render 中多次调用)
unsigned long now_ish() { return millis(); }

// ==================== 屏幕0: 角色屏 ====================
void drawCharacterScreen() {
  int charX = 3 + anim.shakeX;
  int charY = 12 + anim.bounceY;

  // 对话气泡
  if (anim.bubbleText.length() > 0) {
    DefaultChibi::drawBubble(&display, charX + 24, charY,
                              anim.bubbleText.substring(0, 14));
  }

  // 角色本体
  DefaultChibi::draw(&display, charX, charY,
                     sys.char_expression,
                     anim.blinking ? anim.blinkFrame : 0,
                     anim.showHeart, anim.showSweat,
                     anim.zzzOffset, anim.wavePhase);

  // 角色名 + 状态标签
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(48, 12);

  switch (sys.char_expression) {
    case EXP_IDLE:     display.println(F("･ω･")); break;
    case EXP_HAPPY:    display.println(F("^o^")); break;
    case EXP_WORKING:  display.println(F("･_･")); break;
    case EXP_WORRIED:  display.println(F(";_; ")); break;
    case EXP_ANGRY:    display.println(F(">_<")); break;
    case EXP_SLEEP:    display.println(F("-_-")); break;
    case EXP_LOVE:     display.println(F("♡_♡")); break;
    case EXP_GREETING: display.println(F("★o★")); break;
  }

  display.setCursor(48, 22);
  display.println(F("An-chan"));

  // 角色提示
  display.setCursor(48, 34);
  display.setTextColor(SSD1306_WHITE);
  if (sys.sec_level == "danger") {
    display.println(F("⚠ 危险!"));
  } else if (sys.sec_level == "warning") {
    display.println(F("⚡ 注意..."));
  } else if (sys.ai_status == "working") {
    display.println(F("🛡️ 守护中"));
  } else {
    display.println(F("✨ 一切安好"));
  }

  // 底部小字
  display.setCursor(48, 48);
  display.print(F("AI:"));
  display.print(sys.ai_status == "working" ? "WORK" :
                sys.ai_status == "alert" ? "ALERT" :
                sys.ai_status == "offline" ? "OFF" : "IDLE");
}

// ==================== 屏幕1: 安全屏 ====================
void drawSecurityScreen() {
  display.setTextSize(1);
  display.setCursor(2, 12);
  display.println(F("🛡️ Security"));

  // 安全状态大字
  display.setTextSize(2);
  int y = 28;
  if (sys.sec_level == "safe") {
    display.setCursor(30, y);
    display.println(F("SAFE"));
  } else if (sys.sec_level == "warning") {
    display.setCursor(12, y);
    display.println(F("WARNING"));
  } else {
    display.setCursor(18, y);
    display.println(F("DANGER"));
  }

  // 统计
  display.setTextSize(1);
  display.setCursor(2, 50);
  display.print(F("T:"));
  display.print(sys.threat_count);
  display.print(F(" B:"));
  display.print(sys.blocked_count);
  display.print(F(" FW:"));
  display.print(sys.firewall_on ? "Y" : "N");
  display.print(F(" AV:"));
  display.print(sys.defender_on ? "Y" : "N");
}

// ==================== 屏幕2: 网络屏 ====================
void drawNetworkScreen() {
  display.setTextSize(1);
  display.setCursor(2, 12);
  display.println(F("🌐 Network"));

  display.setTextSize(2);
  display.setCursor(15, 26);
  display.print(sys.active_connections);
  display.setTextSize(1);
  display.setCursor(60, 30);
  display.println(F("conns"));

  display.setCursor(2, 44);
  display.print(F("Sus IPs: "));
  display.print(sys.suspicious_ips);

  display.setCursor(2, 54);
  display.print(F("CPU:"));
  display.print((int)sys.cpu_usage);
  display.print(F("% Mem:"));
  display.print((int)sys.mem_usage);
  display.print(F("%"));
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

void handleWiFi() {
  if (!wifiClient || !wifiClient.connected()) {
    wifiClient = wifiServer.available();
    return;
  }
  static String buf = "";
  while (wifiClient.available()) {
    char c = wifiClient.read();
    if (c == '\n') { processCommand(buf); buf = ""; }
    else buf += c;
  }
}

// ==================== 命令处理 ====================
void processCommand(String json) {
  json.trim();
  if (json.length() == 0) return;

  StaticJsonDocument<1536> doc;
  DeserializationError err = deserializeJson(doc, json);
  if (err) {
    Serial.println(F("{\"error\":\"parse\"}"));
    return;
  }

  String cmd = doc["cmd"] | "";

  if (cmd == "update") {
    // 解析状态
    sys.ai_status = doc["ai_status"] | sys.ai_status;
    sys.ai_task = doc["ai_task"] | sys.ai_task;
    sys.ai_progress = doc["ai_progress"] | sys.ai_progress;
    sys.sec_level = doc["sec_level"] | sys.sec_level;
    sys.threat_count = doc["threat_count"] | sys.threat_count;
    sys.blocked_count = doc["blocked_count"] | sys.blocked_count;
    sys.last_threat = doc["last_threat"] | sys.last_threat;
    sys.active_connections = doc["active_connections"] | sys.active_connections;
    sys.suspicious_ips = doc["suspicious_ips"] | sys.suspicious_ips;
    sys.net_status = doc["net_status"] | sys.net_status;
    sys.firewall_on = doc["firewall_on"] | sys.firewall_on;
    sys.defender_on = doc["defender_on"] | sys.defender_on;
    sys.cpu_usage = doc["cpu_usage"] | sys.cpu_usage;
    sys.mem_usage = doc["mem_usage"] | sys.mem_usage;
    sys.uptime = doc["uptime"] | sys.uptime;

    // 消息
    JsonArray msgs = doc["messages"];
    if (msgs) {
      sys.msg_count = 0;
      for (JsonVariant m : msgs) {
        if (sys.msg_count < 5)
          sys.messages[sys.msg_count++] = m.as<String>();
      }
    }

    // 自动更新角色表情
    sys.char_expression = mapStatusToExpression();

    // 自动气泡
    if (sys.sec_level == "danger" && sys.threat_count > 0) {
      sayBubble("检测到威胁!");
    } else if (sys.ai_status == "alert") {
      sayBubble("主人小心!");
    }

    lastDataReceived = millis();
    Serial.println(F("{\"status\":\"ok\"}"));

  } else if (cmd == "ping") {
    lastDataReceived = millis();
    Serial.println(F("{\"status\":\"pong\"}"));

  } else if (cmd == "alert") {
    sys.sec_level = "danger";
    sys.last_threat = doc["message"] | "ALERT";
    sys.char_expression = EXP_ANGRY;
    sayBubble("危险!!!");
    triggerShake();
    beep(5);
    showHeart(false);
    Serial.println(F("{\"status\":\"alert_ack\"}"));

  } else if (cmd == "expression") {
    // 手动设置表情
    int exp = doc["expression"] | -1;
    if (exp >= 0 && exp < 8) {
      sys.char_expression = exp;
      // 表情触发动效
      if (exp == EXP_HAPPY || exp == EXP_LOVE) {
        triggerBounce();
        showHeart(exp == EXP_LOVE);
      }
      if (exp == EXP_WORRIED || exp == EXP_ANGRY) triggerShake();
    }
    Serial.println(F("{\"status\":\"ok\"}"));

  } else if (cmd == "say") {
    // 显示气泡文字
    String text = doc["text"] | "";
    if (text.length() > 0) {
      sayBubble(text);
    }
    Serial.println(F("{\"status\":\"ok\"}"));

  } else if (cmd == "character") {
    // 切换角色模式
    String mode = doc["mode"] | "";
    if (mode == "custom") {
      sys.char_custom = true;
    } else if (mode == "default") {
      sys.char_custom = false;
    }
    // 加载自定义位图数据 (如果需要)
    // ...
    Serial.println(F("{\"status\":\"ok\"}"));

  } else if (cmd == "screen") {
    int sc = doc["screen"] | 0;
    if (sc >= 0 && sc < SCREEN_COUNT) {
      currentScreen = sc;
      lastScreenSwitch = millis();
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

// ==================== 表情映射 ====================
uint8_t mapStatusToExpression() {
  if (sys.sec_level == "danger") return EXP_ANGRY;
  if (sys.sec_level == "warning") return EXP_WORRIED;
  if (sys.ai_status == "working") return EXP_WORKING;
  if (sys.ai_status == "alert") return EXP_WORRIED;
  if (sys.ai_status == "offline") return EXP_SLEEP;
  if (sys.threat_count == 0 && sys.sec_level == "safe")
    return EXP_HAPPY;  // 一切安全 → 开心
  return EXP_IDLE;
}

// ==================== 互动函数 ====================
void sayBubble(const String& text) {
  anim.bubbleText = text;
  anim.bubbleEnd = millis() + 4000;
}

void triggerBounce() {
  anim.bouncing = true;
  anim.bounceV = -4;
  anim.bounceY = 0;
}

void triggerShake() {
  anim.shakeX = 1;
  anim.shakeEnd = millis() + 600;
}

void showHeart(bool show) {
  anim.showHeart = show;
  anim.heartEnd = millis() + 2000;
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
    if (sys.sec_level == "danger") analogWrite(LED_PIN, 255);
    else if (sys.sec_level == "warning") analogWrite(LED_PIN, 128);
    else analogWrite(LED_PIN, 0);
  }
}

void beep(int times) {
  if (BUZZER_PIN < 0) return;
  for (int i = 0; i < times; i++) {
    digitalWrite(BUZZER_PIN, HIGH); delay(80);
    digitalWrite(BUZZER_PIN, LOW); delay(60);
  }
}
