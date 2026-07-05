/*
 * ================================================================
 *  AI 网络安全管家 - TTGO T-Display 固件 (彩色版)
 *  适用于: TTGO T-Display ESP32 (1.14寸彩色TFT)
 *
 *  优势: 彩屏、带按键、可电池供电
 * ================================================================
 *
 * 接线: 使用 T-Display 内置屏幕，无需额外接线
 * 可选外接: 蜂鸣器(D5), WS2812B(D4)
 *
 * 淘宝搜索: "TTGO T-Display ESP32"
 * 参考价格: ¥45-60
 */

#include <TFT_eSPI.h>
#include <ArduinoJson.h>
#include <WiFi.h>

// ==================== 配置 ====================
#define BUZZER_PIN 5
#define LED_PIN 4
#define BUTTON_LEFT 0    // 左按键 (切换屏幕)
#define BUTTON_RIGHT 35  // 右按键
#define WIFI_SSID "YOUR_WIFI"
#define WIFI_PASS "YOUR_PASS"
#define WIFI_ENABLED false
#define SERIAL_BAUD 115200

// ==================== 颜色定义 ====================
#define COLOR_SAFE    0x00FF00   // 绿色
#define COLOR_WARNING 0xFFA500   // 橙色
#define COLOR_DANGER  0xFF0000   // 红色
#define COLOR_BG      0x0A0E17   // 深蓝黑背景
#define COLOR_CARD    0x141B26   // 卡片背景
#define COLOR_TEXT    0xE0E6ED   // 文字色
#define COLOR_ACCENT  0x4A9EFF   // 强调色
#define COLOR_WHITE   0xFFFFFF

// ==================== 全局对象 ====================
TFT_eSPI tft = TFT_eSPI();
WiFiServer wifiServer(8080);
WiFiClient wifiClient;

struct State {
  String ai_status = "idle";
  String ai_task = "";
  int ai_progress = 0;
  String sec_level = "safe";
  int threat_count = 0;
  int blocked_count = 0;
  String last_threat = "";
  int active_connections = 0;
  int suspicious_ips = 0;
  String net_status = "normal";
  bool firewall_on = true;
  bool defender_on = true;
  float cpu_usage = 0;
  float mem_usage = 0;
  long uptime_seconds = 0;
  String messages[5];
  int msg_count = 0;
} state;

int currentScreen = 0;
unsigned long lastScreenSwitch = 0;
unsigned long lastDataReceived = 0;
unsigned long animTimer = 0;
int animFrame = 0;
bool dataTimeout = false;

// ==================== 初始化 ====================
void setup() {
  Serial.begin(SERIAL_BAUD);

  // 初始化屏幕
  tft.init();
  tft.setRotation(1);  // 横屏
  tft.fillScreen(COLOR_BG);
  tft.setTextColor(COLOR_TEXT);

  // 启动画面
  drawBootScreen();

  // 按键
  pinMode(BUTTON_LEFT, INPUT_PULLUP);
  pinMode(BUTTON_RIGHT, INPUT_PULLUP);

  // 外设
  if (BUZZER_PIN >= 0) pinMode(BUZZER_PIN, OUTPUT);
  if (LED_PIN >= 0) pinMode(LED_PIN, OUTPUT);

  // WiFi
  if (WIFI_ENABLED) {
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int tries = 0;
    while (WiFi.status() != WL_CONNECTED && tries++ < 20) delay(500);
    if (WiFi.status() == WL_CONNECTED) wifiServer.begin();
  }

  lastDataReceived = millis();
  lastScreenSwitch = millis();

  Serial.println("{\"status\":\"ready\",\"type\":\"tdisplay\"}");
}

// ==================== 启动画面 ====================
void drawBootScreen() {
  tft.fillScreen(COLOR_BG);
  tft.setTextColor(COLOR_ACCENT);
  tft.setTextSize(3);
  tft.drawString("AI Guard", 20, 40);
  tft.setTextColor(COLOR_TEXT);
  tft.setTextSize(2);
  tft.drawString("Booting...", 30, 80);

  for (int i = 0; i <= 100; i += 10) {
    tft.fillRect(20, 110, i * 2, 8, COLOR_ACCENT);
    delay(80);
  }
  delay(500);
  tft.fillScreen(COLOR_BG);
}

// ==================== 主循环 ====================
void loop() {
  handleSerial();
  if (WIFI_ENABLED) handleWiFi();

  // 按键切换屏幕
  if (digitalRead(BUTTON_LEFT) == LOW) {
    currentScreen = (currentScreen + 1) % 3;
    delay(200);
  }

  // 自动切换
  if (millis() - lastScreenSwitch > 5000) {
    currentScreen = (currentScreen + 1) % 3;
    lastScreenSwitch = millis();
  }

  // 数据超时
  dataTimeout = (millis() - lastDataReceived > 10000);

  // 更新显示
  updateDisplay();
  updateAlerts();

  delay(50);
}

// ==================== 串口处理 ====================
void handleSerial() {
  static String buf = "";
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { processCommand(buf); buf = ""; }
    else buf += c;
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

void processCommand(String json) {
  json.trim();
  if (json.length() == 0) return;

  StaticJsonDocument<1024> doc;
  if (deserializeJson(doc, json)) {
    Serial.println("{\"error\":\"parse\"}");
    return;
  }

  String cmd = doc["cmd"] | "";

  if (cmd == "update") {
    state.ai_status = doc["ai_status"] | state.ai_status;
    state.ai_task = doc["ai_task"] | state.ai_task;
    state.ai_progress = doc["ai_progress"] | state.ai_progress;
    state.sec_level = doc["sec_level"] | state.sec_level;
    state.threat_count = doc["threat_count"] | state.threat_count;
    state.blocked_count = doc["blocked_count"] | state.blocked_count;
    state.last_threat = doc["last_threat"] | state.last_threat;
    state.active_connections = doc["active_connections"] | state.active_connections;
    state.suspicious_ips = doc["suspicious_ips"] | state.suspicious_ips;
    state.net_status = doc["net_status"] | state.net_status;
    state.firewall_on = doc["firewall_on"] | state.firewall_on;
    state.defender_on = doc["defender_on"] | state.defender_on;
    state.cpu_usage = doc["cpu_usage"] | state.cpu_usage;
    state.mem_usage = doc["mem_usage"] | state.mem_usage;
    state.uptime_seconds = doc["uptime"] | state.uptime_seconds;

    JsonArray msgs = doc["messages"];
    if (msgs) {
      state.msg_count = 0;
      for (JsonVariant m : msgs)
        if (state.msg_count < 5)
          state.messages[state.msg_count++] = m.as<String>();
    }

    lastDataReceived = millis();
    Serial.println("{\"status\":\"ok\"}");
  }
  else if (cmd == "ping") {
    lastDataReceived = millis();
    Serial.println("{\"status\":\"pong\"}");
  }
  else if (cmd == "alert") {
    state.sec_level = "danger";
    state.last_threat = doc["message"] | "ALERT";
    beepAlert(3);
    Serial.println("{\"status\":\"alert_ack\"}");
  }
}

// ==================== 显示 ====================
void updateDisplay() {
  tft.fillScreen(COLOR_BG);

  // 顶部状态栏
  drawTopBar();

  // 主体
  switch (currentScreen) {
    case 0: drawAIScreen(); break;
    case 1: drawSecurityScreen(); break;
    case 2: drawNetworkScreen(); break;
  }
}

void drawTopBar() {
  // 背景条
  tft.fillRect(0, 0, 135, 22, COLOR_CARD);

  // 信号图标
  if (dataTimeout) {
    tft.setTextColor(COLOR_DANGER);
    tft.drawString("X", 3, 3);
  } else {
    for (int i = 0; i < 4; i++)
      tft.fillRect(2 + i * 5, 18 - i * 3, 3, 2 + i * 3, COLOR_SAFE);
  }

  // 状态指示灯 (右上角)
  uint16_t ledColor = COLOR_SAFE;
  if (state.sec_level == "danger") ledColor = ((millis() / 300) % 2) ? COLOR_DANGER : COLOR_BG;
  else if (state.sec_level == "warning") ledColor = COLOR_WARNING;
  tft.fillCircle(125, 11, 5, ledColor);

  // 标题
  tft.setTextColor(COLOR_WHITE);
  tft.setTextSize(1);
  tft.drawString("AI Guard", 45, 5);

  // 安全等级标签
  String secLabel = state.sec_level == "danger" ? "DANGER" :
                    state.sec_level == "warning" ? "WARN" : "SAFE";
  tft.setTextColor(state.sec_level == "danger" ? COLOR_DANGER :
                   state.sec_level == "warning" ? COLOR_WARNING : COLOR_SAFE);
  tft.drawString(secLabel, 85, 5);
}

// ==================== 屏幕0: AI状态 ====================
void drawAIScreen() {
  tft.setTextColor(COLOR_ACCENT);
  tft.setTextSize(2);
  tft.drawString("AI Status", 5, 28);

  if (state.ai_status == "idle") {
    tft.setTextColor(COLOR_TEXT);
    tft.drawString("Idle", 5, 55);
    tft.drawString("Ready for tasks", 5, 75);
    // 呼吸圈
    int r = 4 + (sin(millis() * 0.005) + 1) * 2;
    tft.fillCircle(125, 60, r, COLOR_SAFE);
  }
  else if (state.ai_status == "working") {
    tft.setTextColor(COLOR_ACCENT);
    tft.drawString("Working...", 5, 55);
    tft.setTextColor(COLOR_TEXT);
    tft.drawString(state.ai_task.substring(0, 16), 5, 75);
    // 进度条
    if (state.ai_progress > 0) {
      tft.drawRect(5, 100, 125, 12, COLOR_ACCENT);
      tft.fillRect(6, 101, state.ai_progress * 123 / 100, 10, COLOR_ACCENT);
      tft.setTextSize(1);
      tft.drawString(String(state.ai_progress) + "%", 55, 102);
    }
    // 旋转动画
    drawSpinnerTFT(120, 85, 6, animFrame);
  }
  else if (state.ai_status == "alert") {
    tft.setTextColor(COLOR_DANGER);
    tft.drawString("ALERT!", 5, 55);
    tft.setTextColor(COLOR_WARNING);
    tft.drawString("Threat detected", 5, 75);
  }
  else {
    tft.setTextColor(COLOR_DANGER);
    tft.drawString("Offline", 5, 55);
    tft.drawString("No PC connection", 5, 75);
  }

  // 底部
  tft.setTextColor(TFT_DARKGREY);
  tft.drawString("Up: " + formatUptime(state.uptime_seconds), 5, 118);
}

// ==================== 屏幕1: 安全状态 ====================
void drawSecurityScreen() {
  tft.setTextColor(COLOR_ACCENT);
  tft.setTextSize(2);
  tft.drawString("Security", 5, 28);

  // 大安全指示器
  uint16_t secColor = state.sec_level == "danger" ? COLOR_DANGER :
                      state.sec_level == "warning" ? COLOR_WARNING : COLOR_SAFE;
  tft.setTextColor(secColor);
  tft.setTextSize(3);
  String label = state.sec_level == "danger" ? "DANGER" :
                 state.sec_level == "warning" ? "WARNING" : "SAFE";
  tft.drawString(label, 20, 55);

  // 统计
  tft.setTextColor(COLOR_TEXT);
  tft.setTextSize(1);
  String stats = "Threats:" + String(state.threat_count) +
                 "  Blocked:" + String(state.blocked_count);
  tft.drawString(stats, 5, 90);

  // 防护状态条
  int fwColor = state.firewall_on ? COLOR_SAFE : COLOR_DANGER;
  int avColor = state.defender_on ? COLOR_SAFE : COLOR_DANGER;
  tft.fillRect(5, 108, 60, 16, fwColor);
  tft.setTextColor(COLOR_WHITE);
  tft.drawString("FW:ON", 10, 110);
  tft.fillRect(70, 108, 60, 16, avColor);
  tft.drawString("AV:ON", 75, 110);
}

// ==================== 屏幕2: 网络状态 ====================
void drawNetworkScreen() {
  tft.setTextColor(COLOR_ACCENT);
  tft.setTextSize(2);
  tft.drawString("Network", 5, 28);

  tft.setTextColor(COLOR_TEXT);
  tft.setTextSize(3);
  tft.drawString(String(state.active_connections), 15, 55);
  tft.setTextSize(1);
  tft.drawString("connections", 75, 65);

  tft.setTextSize(1);
  tft.setTextColor(COLOR_TEXT);
  tft.drawString("Suspicious IPs: " + String(state.suspicious_ips), 5, 85);

  uint16_t netColor = state.net_status == "under_attack" ? COLOR_DANGER :
                      state.net_status == "suspicious" ? COLOR_WARNING : COLOR_SAFE;
  tft.setTextColor(netColor);
  String netLabel = state.net_status == "under_attack" ? "ATTACK DETECTED" :
                    state.net_status == "suspicious" ? "Suspicious Traffic" : "Traffic Normal";
  tft.drawString(netLabel, 5, 98);

  // CPU / Mem
  tft.setTextColor(COLOR_TEXT);
  tft.drawString("CPU:" + String((int)state.cpu_usage) + "%", 5, 115);
  tft.drawString("Mem:" + String((int)state.mem_usage) + "%", 70, 115);

  // 小进度条
  tft.drawRect(30, 114, 35, 8, COLOR_ACCENT);
  tft.fillRect(31, 115, (int)(state.cpu_usage * 33 / 100), 6,
               state.cpu_usage > 80 ? COLOR_DANGER : COLOR_SAFE);
}

// ==================== 告警 ====================
void updateAlerts() {
  if (BUZZER_PIN >= 0) {
    if (state.sec_level == "danger")
      digitalWrite(BUZZER_PIN, (millis() / 200) % 2);
    else if (state.sec_level == "warning")
      digitalWrite(BUZZER_PIN, (millis() / 800) % 2);
    else
      digitalWrite(BUZZER_PIN, LOW);
  }

  if (LED_PIN >= 0) {
    if (state.sec_level == "danger")
      analogWrite(LED_PIN, 255);
    else if (state.sec_level == "warning")
      analogWrite(LED_PIN, 128);
    else
      analogWrite(LED_PIN, 0);
  }
}

void beepAlert(int times) {
  if (BUZZER_PIN < 0) return;
  for (int i = 0; i < times; i++) {
    digitalWrite(BUZZER_PIN, HIGH); delay(100);
    digitalWrite(BUZZER_PIN, LOW); delay(80);
  }
}

// ==================== 工具函数 ====================
void drawSpinnerTFT(int cx, int cy, int r, int frame) {
  float a = frame * PI / 4;
  int x1 = cx + r * cos(a), y1 = cy + r * sin(a);
  int x2 = cx + r * cos(a + PI), y2 = cy + r * sin(a + PI);
  tft.drawLine(x1, y1, x2, y2, COLOR_ACCENT);
  if (frame > 0) {
    float pa = (frame - 1) * PI / 4;
    int px1 = cx + r * cos(pa), py1 = cy + r * sin(pa);
    int px2 = cx + r * cos(pa + PI), py2 = cy + r * sin(pa + PI);
    for (float t = 0; t < 1; t += 0.3) {
      tft.drawPixel(px1 + t * (px2 - px1), py1 + t * (py2 - py1), TFT_DARKGREY);
    }
  }
}

String formatUptime(long s) {
  if (s < 60) return String(s) + "s";
  long m = s / 60, h = m / 60, d = h / 24;
  if (d > 0) return String(d) + "d" + String(h % 24) + "h";
  if (h > 0) return String(h) + "h" + String(m % 60) + "m";
  return String(m) + "m";
}
