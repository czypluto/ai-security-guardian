/*
 * AI 网络安全管家 - TTGO T-Display 固件 v4.0
 * 双屏: kaomoji表情陪伴 + 状态仪表盘
 * 双缓冲无闪烁
 */

#include <TFT_eSPI.h>
#include <ArduinoJson.h>

// ==================== 配置 ====================
#define BUZZER_PIN 5
#define LED_PIN 12
#define BACKLIGHT_PIN 4
#define BUTTON_LEFT 0
#define BUTTON_RIGHT 35
#define SERIAL_BAUD 115200

// ==================== 颜色 ====================
#define C_SAFE    0x07E0
#define C_WARN    0xFD20
#define C_DANGER  0xF800
#define C_BG      0x0841
#define C_CARD    0x1082
#define C_TEXT    0xD69A
#define C_ACCENT  0x4B7F
#define C_WHITE   0xFFFF
#define C_DGREY   0x632C
#define C_PINK    0xFAC9
#define C_TEAL    0x3D8E

TFT_eSPI tft = TFT_eSPI();
TFT_eSprite spr = TFT_eSprite(&tft);

struct State {
  String sec_level = "safe";
  int threat_count = 0;
  int blocked_count = 0;
  int active_connections = 0;
  int suspicious_ips = 0;
  String net_status = "normal";
  bool firewall_on = true;
  bool defender_on = true;
  float cpu_usage = 0;
  float mem_usage = 0;
  long uptime_seconds = 0;
  String bubble = "";
  unsigned long bubbleTime = 0;
} state;

int currentScreen = 0;
unsigned long lastDataReceived = 0;
unsigned long lastDisplayUpdate = 0;
int animFrame = 0;
bool dataTimeout = false;
bool displayDirty = true;

// ==================== 初始化 ====================
void setup() {
  Serial.begin(SERIAL_BAUD);
  tft.init();
  tft.setRotation(1);
  spr.setColorDepth(16);
  spr.createSprite(135, 240);

  pinMode(BACKLIGHT_PIN, OUTPUT);
  digitalWrite(BACKLIGHT_PIN, HIGH);

  tft.fillScreen(C_BG);
  tft.setTextColor(C_ACCENT, C_BG);
  tft.setTextSize(3);
  tft.drawString("AI Guard", 15, 40);
  tft.setTextColor(C_TEXT, C_BG);
  tft.setTextSize(2);
  tft.drawString("Booting...", 25, 80);
  for (int i = 0; i <= 100; i += 10) {
    tft.fillRect(15, 110, i * 2, 8, C_ACCENT);
    delay(80);
  }
  delay(300);
  tft.fillScreen(C_BG);

  pinMode(BUTTON_LEFT, INPUT_PULLUP);
  pinMode(BUTTON_RIGHT, INPUT);
  if (BUZZER_PIN >= 0) pinMode(BUZZER_PIN, OUTPUT);
  if (LED_PIN >= 0) pinMode(LED_PIN, OUTPUT);

  lastDataReceived = millis();
  Serial.println("{\"status\":\"ready\",\"type\":\"tdisplay\"}");
}

// ==================== 主循环 ====================
void loop() {
  handleSerial();

  if (digitalRead(BUTTON_LEFT) == LOW) {
    currentScreen = !currentScreen;
    displayDirty = true;
    delay(250);
  }

  bool wasTimeout = dataTimeout;
  dataTimeout = (millis() - lastDataReceived > 10000);
  if (dataTimeout != wasTimeout) displayDirty = true;

  animFrame = (animFrame + 1) % 32;

  if (displayDirty || millis() - lastDisplayUpdate > 800) {
    spr.fillScreen(C_BG);
    if (currentScreen == 0) drawEmojiScreen();
    else drawStatusScreen();
    spr.pushSprite(0, 0);
    lastDisplayUpdate = millis();
    displayDirty = false;
  }

  updateAlerts();
  delay(30);
}

// ==================== 屏幕0: Kaomoji 表情 ====================
void drawEmojiScreen() {
  String exp = state.sec_level;
  int t = millis();

  // ---- 背景装饰 ----
  // 安全时画几个小星星
  if (exp == "safe") {
    for (int i = 0; i < 5; i++) {
      int sx = 10 + (i * 25) + (sin(t*0.003 + i) * 8);
      int sy = 14 + (cos(t*0.005 + i) * 6);
      spr.fillCircle(sx, sy, 2, C_WARN);
    }
  }
  // 危险时红色闪烁边框
  if (exp == "danger" && (t / 500) % 2) {
    spr.drawRoundRect(5, 5, 125, 115, 8, C_DANGER);
    spr.drawRoundRect(6, 6, 123, 113, 8, C_DANGER);
  }

  // ---- 表情主体 ----
  spr.setTextSize(4);
  spr.setTextColor(C_WHITE, C_BG);

  String face;
  if (dataTimeout) {
    face = "(-_-)";           // 断连睡觉
    spr.setTextColor(C_DGREY, C_BG);
  } else if (exp == "danger") {
    face = "(>_<)";           // 危险
    spr.setTextColor(C_DANGER, C_BG);
  } else if (exp == "warning") {
    face = "(;_;)";           // 担心
    spr.setTextColor(C_WARN, C_BG);
  } else {
    face = "(^_^)";           // 开心
    spr.setTextColor(C_SAFE, C_BG);
  }

  // 居中绘制表情
  int fw = spr.textWidth(face);
  spr.drawString(face, (135 - fw) / 2, 35);

  // ---- 装饰文字 ----
  spr.setTextSize(2);
  if (dataTimeout) {
    spr.setTextColor(C_DGREY, C_BG);
    spr.drawString("zzZ...", 42, 70);
  } else if (exp == "danger") {
    spr.setTextColor(C_DANGER, C_BG);
    spr.drawString("DANGER!", 30, 70);
  } else if (exp == "warning") {
    spr.setTextColor(C_WARN, C_BG);
    spr.drawString("Checking...", 20, 70);
  } else {
    spr.setTextColor(C_SAFE, C_BG);
    spr.drawString("All Good~", 25, 70);
  }

  // ---- 气泡 ----
  drawBubble();

  // 底部
  spr.setTextColor(C_DGREY, C_BG);
  spr.setTextSize(1);
  spr.drawString("< to status", 35, 126);
}

void drawBubble() {
  String text = state.bubble;
  if (text.length() > 0 && millis() - state.bubbleTime > 4500) {
    text = "";
    state.bubble = "";
  }
  if (text.length() == 0) {
    if (dataTimeout) text = "主人还在吗...";
    else if (state.sec_level == "danger") text = "危险!快处理!";
    else if (state.sec_level == "warning") text = "有可疑情况...";
    else text = "今天也很安全~";
  }

  spr.fillRoundRect(5, 97, 125, 24, 6, C_WHITE);
  spr.drawRoundRect(5, 97, 125, 24, 6, C_CARD);
  spr.fillTriangle(55, 121, 62, 121, 50, 127, C_WHITE);

  spr.setTextColor(C_BG, C_WHITE);
  spr.setTextSize(1);
  spr.drawString(text.substring(0, 22), 9, 103);
}

// ==================== 屏幕1: 状态仪表盘 ====================
void drawStatusScreen() {
  int y = 26;

  spr.setTextColor(C_ACCENT, C_BG);
  spr.setTextSize(2);
  spr.drawString("Status", 5, y);
  y += 22;

  // 安全等级大卡片
  uint16_t sc = state.sec_level == "danger" ? C_DANGER :
                state.sec_level == "warning" ? C_WARN : C_SAFE;
  spr.fillRoundRect(3, y, 129, 24, 6, sc);
  spr.setTextColor(C_WHITE, sc);
  spr.setTextSize(2);
  String st = state.sec_level == "danger" ? "! DANGER !" :
              state.sec_level == "warning" ? "WARNING" : "SECURE";
  spr.drawString(st, (135-spr.textWidth(st))/2, y+3);
  y += 30;

  // 统计
  spr.setTextColor(C_TEXT, C_BG);
  spr.setTextSize(1);
  spr.drawString("Threats:" + String(state.threat_count), 5, y);
  spr.drawString("Blocked:" + String(state.blocked_count), 70, y);
  y += 18;
  spr.drawString("Conn:" + String(state.active_connections), 5, y);
  String nl = state.net_status == "under_attack" ? "ATTACK" :
              state.net_status == "suspicious" ? "Suspicious" : "Normal";
  uint16_t nc = state.net_status == "under_attack" ? C_DANGER :
                state.net_status == "suspicious" ? C_WARN : C_SAFE;
  spr.setTextColor(nc, C_BG);
  spr.drawString(nl, 70, y);
  y += 20;

  // 防火墙/杀毒
  spr.fillRoundRect(3, y, 62, 16, 4, state.firewall_on ? C_SAFE : C_DANGER);
  spr.setTextColor(C_WHITE, state.firewall_on ? C_SAFE : C_DANGER);
  spr.drawString("FW:ON", 8, y+2);
  spr.fillRoundRect(70, y, 62, 16, 4, state.defender_on ? C_SAFE : C_DANGER);
  spr.setTextColor(C_WHITE, state.defender_on ? C_SAFE : C_DANGER);
  spr.drawString("AV:ON", 75, y+2);
  y += 22;

  // CPU
  spr.setTextColor(C_TEXT, C_BG);
  spr.drawString("CPU", 3, y);
  spr.drawRect(30, y, 78, 7, C_ACCENT);
  spr.fillRect(31, y+1, (int)(state.cpu_usage*76/100), 5,
               state.cpu_usage>80?C_DANGER:state.cpu_usage>60?C_WARN:C_SAFE);
  spr.drawString(String((int)state.cpu_usage)+"%", 112, y);
  y += 12;

  // MEM
  spr.drawString("MEM", 3, y);
  spr.drawRect(30, y, 78, 7, C_ACCENT);
  spr.fillRect(31, y+1, (int)(state.mem_usage*76/100), 5,
               state.mem_usage>80?C_DANGER:state.mem_usage>60?C_WARN:C_SAFE);
  spr.drawString(String((int)state.mem_usage)+"%", 112, y);
  y += 16;

  spr.setTextColor(C_DGREY, C_BG);
  spr.drawString("Up: " + fmtUptime(state.uptime_seconds), 5, y);
  spr.drawString("< to emoji", 70, y);
}

String fmtUptime(long s) {
  if (s<60) return String(s)+"s";
  long m=s/60,h=m/60,d=h/24;
  if(d>0) return String(d)+"d"+String(h%24)+"h";
  if(h>0) return String(h)+"h"+String(m%60)+"m";
  return String(m)+"m";
}

// ==================== 串口 ====================
void handleSerial() {
  static String buf = "";
  while (Serial.available()) {
    char c = Serial.read();
    if (c=='\n') { processCommand(buf); buf=""; }
    else buf += c;
  }
}

void processCommand(String json) {
  json.trim();
  if (json.length()==0) return;
  StaticJsonDocument<1024> doc;
  if (deserializeJson(doc, json)) return;

  String cmd = doc["cmd"] | "";
  if (cmd == "update") {
    state.sec_level = doc["sec_level"] | state.sec_level;
    state.threat_count = doc["threat_count"] | state.threat_count;
    state.blocked_count = doc["blocked_count"] | state.blocked_count;
    state.active_connections = doc["active_connections"] | state.active_connections;
    state.suspicious_ips = doc["suspicious_ips"] | state.suspicious_ips;
    state.net_status = doc["net_status"] | state.net_status;
    state.firewall_on = doc["firewall_on"] | state.firewall_on;
    state.defender_on = doc["defender_on"] | state.defender_on;
    state.cpu_usage = doc["cpu_usage"] | state.cpu_usage;
    state.mem_usage = doc["mem_usage"] | state.mem_usage;
    state.uptime_seconds = doc["uptime"] | state.uptime_seconds;
    lastDataReceived = millis();
    displayDirty = true;
    Serial.println("{\"status\":\"ok\"}");
  } else if (cmd == "ping") {
    lastDataReceived = millis();
    displayDirty = true;
    Serial.println("{\"status\":\"pong\"}");
  } else if (cmd == "say") {
    state.bubble = doc["text"] | "";
    state.bubbleTime = millis();
    currentScreen = 0;
    displayDirty = true;
    Serial.println("{\"status\":\"ok\"}");
  } else if (cmd == "screen") {
    currentScreen = doc["screen"] | 0;
    displayDirty = true;
    Serial.println("{\"status\":\"ok\"}");
  } else if (cmd == "alert") {
    state.sec_level = "danger";
    state.bubble = doc["message"] | "ALERT!";
    state.bubbleTime = millis();
    currentScreen = 0;
    displayDirty = true;
    beepAlert(3);
    Serial.println("{\"status\":\"alert_ack\"}");
  }
}

void updateAlerts() {
  if (BUZZER_PIN >= 0) {
    if (state.sec_level=="danger") digitalWrite(BUZZER_PIN,(millis()/200)%2);
    else if (state.sec_level=="warning") digitalWrite(BUZZER_PIN,(millis()/800)%2);
    else digitalWrite(BUZZER_PIN,LOW);
  }
  if (LED_PIN >= 0) {
    if (state.sec_level=="danger") analogWrite(LED_PIN,255);
    else if (state.sec_level=="warning") analogWrite(LED_PIN,128);
    else analogWrite(LED_PIN,0);
  }
}
void beepAlert(int times) {
  if (BUZZER_PIN<0) return;
  for(int i=0;i<times;i++){digitalWrite(BUZZER_PIN,HIGH);delay(100);digitalWrite(BUZZER_PIN,LOW);delay(80);}
}
