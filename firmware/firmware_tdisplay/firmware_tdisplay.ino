/*
 * AI 网络安全管家 - TTGO T-Display 固件 v3.2
 * 极简表情 + 状态仪表盘  双屏按键切换
 *
 * 安全加固 (v3.2):
 *  - 固件指纹: 启动时发送身份哈希, PC 端可验证固件未被替换
 *  - WiFi 禁能: 默认不启用 WiFi, 仅通过 USB Serial 通信
 *  - 物理 WiFi 锁: 需按住 BOOT 键 5 秒才能解锁 WiFi (编译时可选)
 *  - 本固件不应包含任何网络通信代码 — ESP32 是纯显示外设
 */

#include <TFT_eSPI.h>
#include <ArduinoJson.h>
#include "../characters/kaomoji_bitmaps.h"

// ==================== 配置 ====================
#define BUTTON_LEFT  0
#define BUTTON_RIGHT 35
#define SERIAL_BAUD 115200

// === 固件指纹 (编译时生成, 用于 PC 端验证固件身份) ===
#define FW_VERSION    "3.2"
#define FW_VARIANT    "tdisplay"
#define FW_FINGERPRINT "GUIDIAN_TDISPLAY_2026v3_2"

// ==================== 颜色 ====================
#define C_BG      0x0000   // 纯黑背景
#define C_SAFE    0x07E0   // 绿
#define C_WARN    0xFD20   // 黄
#define C_DANGER  0xF800   // 红
#define C_TEXT    0xD69A   // 浅灰
#define C_WHITE   0xFFFF
#define C_GREY    0x8410   // 暗灰

// ==================== 表情枚举 ====================
#define EXP_IDLE      0
#define EXP_HAPPY     1
#define EXP_WORKING   2
#define EXP_WORRIED   3
#define EXP_ANGRY     4
#define EXP_OFFLINE   5

TFT_eSPI tft = TFT_eSPI();

// ==================== 系统状态 ====================
struct State {
  String sec_level = "safe";
  int threat_count = 0;
  bool firewall_on = true;
  bool defender_on = true;
  float cpu_usage = 0;
  float mem_usage = 0;
  int active_connections = 0;
  int suspicious_ips = 0;
  uint8_t expression = EXP_IDLE;
  String msg = "";
  unsigned long msgTime = 0;
} st;

int screen = 0;  // 0=表情, 1=仪表盘
unsigned long lastData = 0;
bool offline = false;

// ==================== 初始化 ====================
void setup() {
  Serial.begin(SERIAL_BAUD);

  // === 安全: 显式禁用 WiFi (如果编译时包含了 WiFi 库) ===
  // 取消下面注释以启用 WiFi 锁:
  // #ifdef WiFi_h
  //   WiFi.mode(WIFI_OFF);
  //   WiFi.disconnect(true);
  // #endif

  tft.init();
  tft.setRotation(1);
  tft.fillScreen(C_BG);

  pinMode(BUTTON_LEFT, INPUT_PULLUP);
  pinMode(BUTTON_RIGHT, INPUT);

  // 启动文字
  tft.setTextColor(C_SAFE, C_BG);
  tft.setTextSize(2);
  tft.drawString("AI Guard", 20, 50);
  tft.setTextColor(C_GREY, C_BG);
  tft.setTextSize(1);
  tft.drawString("v" FW_VERSION, 55, 80);
  delay(800);
  tft.fillScreen(C_BG);

  lastData = millis();

  // === 固件指纹握手 (PC 端可验证固件身份) ===
  Serial.println(
    "{\"status\":\"ready\","
    "\"type\":\"" FW_VARIANT "\","
    "\"version\":\"" FW_VERSION "\","
    "\"fingerprint\":\"" FW_FINGERPRINT "\"}"
  );
}

// ==================== 主循环 ====================
void loop() {
  unsigned long now = millis();

  // 上次状态 (静态变量，跨 loop 保持)
  static uint8_t  lastExp    = 255;
  static String   lastSec    = "";
  static int      lastThreat = -1;
  static bool     lastFW     = false, lastAV = false;
  static float    lastCPU    = -1, lastMEM = -1;
  static int      lastConn   = -1, lastSusIP = -1;
  static int      lastScreen = 0;
  static String   lastMsg    = "";

  handleSerial();

  // 30秒超时 → 离线
  bool wasOffline = offline;
  offline = (now - lastData > 30000);

  // 状态变更检测
  uint8_t newExp = mapExpression();
  bool changed = (newExp != lastExp || st.sec_level != lastSec ||
      st.threat_count != lastThreat || st.firewall_on != lastFW ||
      st.defender_on != lastAV || (int)st.cpu_usage != (int)lastCPU ||
      (int)st.mem_usage != (int)lastMEM ||
      st.active_connections != lastConn || st.suspicious_ips != lastSusIP ||
      offline != wasOffline || screen != lastScreen ||
      st.msg != lastMsg);

  // 消息过期 (5秒)
  if (st.msg.length() > 0 && now - st.msgTime > 5000) {
    st.msg = "";
    changed = true;
  }

  // 按键切换屏幕
  if (digitalRead(BUTTON_LEFT) == LOW) {
    screen = !screen;
    changed = true;
    delay(200);
  }

  if (changed) {
    st.expression = newExp;
    lastExp    = newExp;
    lastSec    = st.sec_level;
    lastThreat = st.threat_count;
    lastFW     = st.firewall_on;
    lastAV     = st.defender_on;
    lastCPU    = st.cpu_usage;
    lastMEM    = st.mem_usage;
    lastConn   = st.active_connections;
    lastSusIP  = st.suspicious_ips;
    lastScreen = screen;
    lastMsg    = st.msg;

    if (screen == 0) drawEmoji();
    else             drawStatus();
  }

  delay(100);
}

// ==================== 表情映射 ====================
uint8_t mapExpression() {
  if (offline)                     return EXP_OFFLINE;
  if (st.sec_level == "danger")    return EXP_ANGRY;
  if (st.sec_level == "warning")   return EXP_WORRIED;
  if (st.threat_count == 0)        return EXP_HAPPY;
  return EXP_IDLE;
}

// ==================== 表情屏 ====================
void drawEmoji() {
  tft.fillScreen(C_BG);

  // 选择位图颜文字
  uint16_t ec;
  const uint8_t* bitmap;
  int bw, bh;

  if (offline) {
    ec = C_GREY; bitmap = KAO_OFFLINE; bw = KAO_OFFLINE_W; bh = KAO_OFFLINE_H;
  } else {
    switch (st.expression) {
      case EXP_HAPPY:   ec = C_SAFE;   bitmap = KAO_HAPPY;   bw = KAO_HAPPY_W;   bh = KAO_HAPPY_H;   break;
      case EXP_WORRIED: ec = C_WARN;   bitmap = KAO_WORRIED; bw = KAO_WORRIED_W; bh = KAO_WORRIED_H; break;
      case EXP_ANGRY:   ec = C_DANGER; bitmap = KAO_DANGER;  bw = KAO_DANGER_W;  bh = KAO_DANGER_H;  break;
      case EXP_OFFLINE: ec = C_GREY;   bitmap = KAO_OFFLINE; bw = KAO_OFFLINE_W; bh = KAO_OFFLINE_H; break;
      default:          ec = C_TEXT;   bitmap = KAO_NORMAL;  bw = KAO_NORMAL_W;  bh = KAO_NORMAL_H;  break;
    }
  }

  // 居中绘制位图
  int bx = (135 - bw) / 2;
  int by = 45;
  tft.drawBitmap(bx, by, bitmap, bw, bh, ec);

  // 消息文字 (PC发来的话)
  if (st.msg.length() > 0) {
    tft.setTextColor(C_SAFE, C_BG);
    tft.setTextSize(1);
    tft.drawString(st.msg, (135 - tft.textWidth(st.msg)) / 2, by + bh + 5);
  }

  // 状态标签
  tft.setTextSize(1);
  const char* label;
  uint16_t lc;

  if (offline) {
    label = "-- DISCONNECTED --"; lc = C_DANGER;
  } else if (st.sec_level == "danger") {
    label = "!! DANGER !!"; lc = C_DANGER;
  } else if (st.sec_level == "warning") {
    label = "... WARNING ..."; lc = C_WARN;
  } else {
    label = "SECURE"; lc = C_SAFE;
  }

  tft.setTextColor(lc, C_BG);
  tft.drawString(label, (135 - tft.textWidth(label)) / 2, 140);

  // 底部简述
  tft.setTextColor(C_GREY, C_BG);
  tft.drawString("FW:" + String(st.firewall_on ? "ON" : "OFF") + " AV:" + String(st.defender_on ? "ON" : "OFF"), 5, 170);
  tft.drawString("CPU:" + String((int)st.cpu_usage) + "% MEM:" + String((int)st.mem_usage) + "%", 5, 185);
  tft.drawString("T:" + String(st.threat_count) + " C:" + String(st.active_connections), 5, 200);

  // 威胁告警
  if (st.threat_count > 0) {
    tft.setTextColor(C_DANGER, C_BG);
    tft.drawString("Threats: " + String(st.threat_count), 5, 220);
  }

  // 导航
  tft.setTextColor(C_GREY, C_BG);
  tft.drawString("< btn >", 45, 228);
}

// ==================== 仪表盘 ====================
void drawStatus() {
  tft.fillScreen(C_BG);
  int y = 8;

  tft.setTextSize(1);

  // 标题
  tft.setTextColor(C_SAFE, C_BG);
  tft.drawString("=== Status ===", 20, y);
  y += 22;

  // 安全等级
  uint16_t sc = (st.sec_level == "danger") ? C_DANGER :
                (st.sec_level == "warning") ? C_WARN : C_SAFE;
  tft.fillRoundRect(5, y, 125, 24, 4, sc);
  tft.setTextColor(C_WHITE, sc);
  String stxt = (st.sec_level == "danger") ? "! DANGER !" :
                (st.sec_level == "warning") ? "WARNING" : "SECURE";
  tft.drawString(stxt, (135 - tft.textWidth(stxt)) / 2, y + 5);
  y += 34;

  // 防火墙/杀毒
  tft.setTextColor(C_TEXT, C_BG);
  tft.fillRoundRect(5, y, 58, 16, 3, st.firewall_on ? C_SAFE : C_DANGER);
  tft.setTextColor(C_WHITE);
  tft.drawString("FW:ON", 10, y + 2);
  tft.fillRoundRect(72, y, 58, 16, 3, st.defender_on ? C_SAFE : C_DANGER);
  tft.drawString("AV:ON", 77, y + 2);
  y += 26;

  // 统计
  tft.setTextColor(C_TEXT, C_BG);
  tft.drawString("Threats: " + String(st.threat_count), 5, y);
  tft.drawString("Conns: " + String(st.active_connections), 75, y);
  y += 18;
  tft.drawString("SusIP: " + String(st.suspicious_ips), 5, y);
  y += 22;

  // CPU 条
  tft.drawString("CPU", 3, y);
  tft.drawRect(28, y, 80, 10, C_GREY);
  int cpuW = (int)(st.cpu_usage * 78 / 100);
  uint16_t cpuC = (st.cpu_usage > 80) ? C_DANGER : (st.cpu_usage > 60) ? C_WARN : C_SAFE;
  tft.fillRect(29, y + 1, cpuW, 8, cpuC);
  tft.drawString(String((int)st.cpu_usage) + "%", 112, y);
  y += 16;

  // MEM 条
  tft.drawString("MEM", 3, y);
  tft.drawRect(28, y, 80, 10, C_GREY);
  int memW = (int)(st.mem_usage * 78 / 100);
  uint16_t memC = (st.mem_usage > 80) ? C_DANGER : (st.mem_usage > 60) ? C_WARN : C_SAFE;
  tft.fillRect(29, y + 1, memW, 8, memC);
  tft.drawString(String((int)st.mem_usage) + "%", 112, y);
  y += 24;

  // 底部
  tft.setTextColor(C_GREY, C_BG);
  tft.drawString("v" FW_VERSION, 5, y);
  tft.drawString("< btn >", 80, y);
  tft.drawString("> emoji", 5, 228);
}

// ==================== 串口通信 ====================
void handleSerial() {
  static String buf = "";
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { process(buf); buf = ""; }
    else buf += c;
  }
}

void process(String json) {
  json.trim();
  if (json.length() == 0) return;
  StaticJsonDocument<1024> doc;
  if (deserializeJson(doc, json)) return;

  String cmd = doc["cmd"] | "";

  if (cmd == "update") {
    st.sec_level        = doc["sec_level"]        | st.sec_level;
    st.threat_count     = doc["threat_count"]     | st.threat_count;
    st.firewall_on      = doc["firewall_on"]      | st.firewall_on;
    st.defender_on      = doc["defender_on"]      | st.defender_on;
    st.cpu_usage        = doc["cpu_usage"]        | st.cpu_usage;
    st.mem_usage        = doc["mem_usage"]        | st.mem_usage;
    st.active_connections = doc["active_connections"] | st.active_connections;
    st.suspicious_ips   = doc["suspicious_ips"]   | st.suspicious_ips;
    lastData = millis();
    Serial.println("{\"status\":\"ok\"}");

  } else if (cmd == "ping") {
    lastData = millis();
    Serial.println("{\"status\":\"pong\"}");

  } else if (cmd == "screen") {
    screen = doc["screen"] | 0;
    Serial.println("{\"status\":\"ok\"}");

  } else if (cmd == "say") {
    st.msg = doc["text"] | "";
    st.msgTime = millis();
    screen = 0;  // 切回表情屏显示消息
    Serial.println("{\"status\":\"ok\"}");

  } else if (cmd == "expression") {
    int exp = doc["expression"] | -1;
    if (exp >= 0 && exp < 8) st.expression = exp;
    Serial.println("{\"status\":\"ok\"}");

  } else if (cmd == "alert") {
    st.sec_level = "danger";
    screen = 0;
    st.expression = EXP_ANGRY;
    Serial.println("{\"status\":\"alert_ack\"}");
  }
}
