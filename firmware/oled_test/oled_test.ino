/*
 * OLED 测试 v2 — 完全匹配 v2.0 初始化顺序
 */
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SDA 21
#define SCL 22

Adafruit_SSD1306 display(128, 64, &Wire, -1);

void setup() {
  Serial.begin(115200);
  delay(200);

  // === 完全匹配 v2.0 初始化 ===
  Wire.begin(SDA, SCL);
  delay(10);

  // 先试 EXTERNALVCC (部分模块需要外供电模式)，再试 SWITCHCAPVCC
  bool ok = display.begin(SSD1306_EXTERNALVCC, 0x3C);
  Serial.print("OLED EXT 0x3C: "); Serial.println(ok ? "OK" : "FAIL");
  if (ok) goto init_done;

  ok = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  Serial.print("OLED SW  0x3C: "); Serial.println(ok ? "OK" : "FAIL");
  if (ok) goto init_done;

  ok = display.begin(SSD1306_EXTERNALVCC, 0x3D);
  Serial.print("OLED EXT 0x3D: "); Serial.println(ok ? "OK" : "FAIL");
  if (ok) goto init_done;

  ok = display.begin(SSD1306_SWITCHCAPVCC, 0x3D);
  Serial.print("OLED SW  0x3D: "); Serial.println(ok ? "OK" : "FAIL");

init_done:

  if (ok) {
    display.clearDisplay();
    // 画测试内容
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println("OLED v2 Test");
    display.println("v2.0 init match");
    display.drawLine(0, 20, 128, 20, SSD1306_WHITE);
    display.setCursor(0, 26);
    display.print("Addr: 0x");
    display.println(ok ? "OK" : "??");
    // 外框
    display.drawRect(0, 0, 127, 63, SSD1306_WHITE);
    display.display();
    Serial.println("Test screen drawn.");
  }

  // I2C 扫描放在 init 之后
  Serial.println("I2C bus scan:");
  for (byte a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.print("  0x"); Serial.println(a, HEX);
    }
  }
}

void loop() {
  static unsigned long last = 0;
  if (millis() - last > 5000) {
    last = millis();
    Serial.println("alive");
  }
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'i') { display.invertDisplay(true); display.display(); Serial.println("i"); }
    if (c == 'n') { display.invertDisplay(false); display.display(); Serial.println("n"); }
    if (c == 'f') { display.fillScreen(SSD1306_WHITE); display.display(); Serial.println("f"); }
    if (c == 'c') { display.clearDisplay(); display.display(); Serial.println("c"); }
  }
}
