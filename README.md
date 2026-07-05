# 🛡️ AI 网络安全管家

> 一个基于 ESP32 + OLED 的微型嵌入式设备，实时显示 AI 助手状态和电脑安全情况
> 全部零件可在淘宝买到，自己动手组装，成本仅 ¥30-100

---

## 📸 效果预览

```
设备外观 (0.96寸 OLED 屏):
┌──────────────────────┐
│ ▂▃▄▅ ●           SAFE│  ← 信号条 + 安全指示灯
│────────────────────│
│                      │
│   🤖 AI Status       │  ← 屏幕0: AI状态
│   Status: 🧠 Working │
│   Progress: 67%      │
│   ████████░░░░  67%  │
│                      │
│   Up: 3h24m          │  ← 运行时间
└──────────────────────┘

自动切换 ↓ (4秒)

┌──────────────────────┐
│ ▂▃▄▅ ●           SAFE│
│────────────────────│
│                      │
│  🛡️ Security         │  ← 屏幕1: 安全状态
│                      │
│     SAFE             │
│                      │
│  Threats: 0 | Blk: 12│
│  FW:ON | AV:ON       │  ← 防火墙+杀毒状态
└──────────────────────┘

自动切换 ↓ (4秒)

┌──────────────────────┐
│ ▂▃▄▅ ●           SAFE│
│────────────────────│
│                      │
│  🌐 Network          │  ← 屏幕2: 网络状态
│      42 conns        │
│  Suspicious IPs: 0   │
│  Traffic: ✓ Normal   │
│                      │
│  CPU:23% Mem:45%     │  ← 系统资源
└──────────────────────┘
```

**检测到威胁时：**

```
┌──────────────────────┐
│ ▂▃▄▅ 🔴(闪)    DANGER│  ← 红色指示灯闪烁
│══════════════════════│  ← 双线边框 (告警)
│                      │
│  🛡️ Security         │
│                      │
│   ⚠ DANGER ⚠         │  ← 危险警告
│                      │
│  Threats: 3 | Blk: 12│
│  FW:ON | AV:ON       │
└──────────────────────┘

同时: 蜂鸣器响 + RGB LED 变红
```

---

## 🏗️ 系统架构

```
┌──────────────────────────────────────────────────┐
│                    你的电脑 (Windows)               │
│                                                    │
│  ┌──────────────────────────────────────────────┐ │
│  │         PC Agent (Python)                     │ │
│  │                                              │ │
│  │  ┌──────────┐  ┌───────────┐  ┌───────────┐ │ │
│  │  │ 安全监控  │  │ 网络监控   │  │ 进程监控   │ │ │
│  │  │Security   │  │ Network   │  │ Process   │ │ │
│  │  │Monitor    │  │Monitor    │  │Monitor    │ │ │
│  │  └────┬─────┘  └─────┬─────┘  └─────┬─────┘ │ │
│  │       │              │              │        │ │
│  │       └──────────────┼──────────────┘        │ │
│  │                      ▼                       │ │
│  │              ┌──────────────┐                │ │
│  │              │  主控制器     │                │ │
│  │              │  Controller  │                │ │
│  │              └──────┬───────┘                │ │
│  │                     │                        │ │
│  │         ┌───────────┼───────────┐            │ │
│  │         ▼           ▼           ▼            │ │
│  │   ┌──────────┐ ┌─────────┐ ┌─────────┐      │ │
│  │   │设备桥接   │ │Web仪表盘│ │系统托盘  │      │ │
│  │   │Device    │ │Dashboard│ │Tray     │      │ │
│  │   │Bridge    │ │:5000    │ │App      │      │ │
│  │   └────┬─────┘ └─────────┘ └─────────┘      │ │
│  └────────┼────────────────────────────────────┘ │
│           │ USB Serial / WiFi                    │
│           ▼                                      │
│  ┌─────────────────────────────┐                 │
│  │   ESP32 开发板               │                 │
│  │   ┌───────────────────────┐ │                 │
│  │   │  0.96" OLED 显示屏     │ │                 │
│  │   │  ┌─────────────────┐  │ │                 │
│  │   │  │ 安全状态/威胁/   │  │ │                 │
│  │   │  │ AI状态/网络信息  │  │ │                 │
│  │   │  └─────────────────┘  │ │                 │
│  │   └───────────────────────┘ │                 │
│  │   🔴 RGB LED  |  🔊 蜂鸣器  │ (可选)          │
│  └─────────────────────────────┘                 │
│                                                    │
│   🖥️  Web Dashboard (浏览器访问 :5000)              │
└──────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 1. 购买零件

参见 **[📦 淘宝零件清单](docs/parts_list.md)**，总价 ¥30-100。

**最简单的入门方案 (¥33):**
- ESP32 开发板 ×1 (¥15)
- 0.96" OLED 屏 ×1 (¥10)
- 杜邦线 母对母 ×4 (¥3)
- USB 数据线 ×1 (¥5)

### 2. 组装

参见 **[🔧 组装指南](docs/assembly_guide.md)**，接线只需4根线：

```
OLED GND → ESP32 GND
OLED VCC → ESP32 3.3V
OLED SCL → ESP32 D22
OLED SDA → ESP32 D21
```

### 3. 烧录固件

1. 安装 [Arduino IDE](https://www.arduino.cc/en/software)
2. 安装 ESP32 开发板支持
3. 安装 `Adafruit SSD1306` 和 `ArduinoJson` 库
4. 打开 `firmware/firmware.ino`，点击上传

### 4. 安装 PC 端

```bash
# 克隆/进入项目目录
cd pc_agent

# 安装 Python 依赖
pip install -r requirements.txt

# 运行!
python main.py
```

或直接运行 `installer/setup.bat` 一键安装。

---

## 📂 项目结构

```
ai-security-guardian/
├── README.md                    # 本文件
├── docs/
│   ├── parts_list.md            # 📦 淘宝零件清单
│   └── assembly_guide.md        # 🔧 组装指南
├── firmware/
│   └── firmware.ino             # 🔌 ESP32 固件 (Arduino)
├── pc_agent/                    # 💻 PC 端 Python 代理
│   ├── main.py                  #    主入口
│   ├── config.yaml              #    配置文件
│   ├── requirements.txt         #    Python 依赖
│   ├── device_bridge.py         #    设备通信 (Serial/WiFi)
│   ├── security_monitor.py      #    安全事件监控
│   ├── network_monitor.py       #    网络威胁检测
│   ├── process_monitor.py       #    可疑进程检测
│   ├── firewall_checker.py      #    防火墙/Defender检查
│   ├── ai_status.py             #    AI 状态追踪
│   ├── web_dashboard.py         #    Web 仪表盘
│   ├── system_tray.py           #    系统托盘
│   └── __init__.py              #    包初始化
├── enclosure/
│   └── case_design.md           # 🖨️  3D 打印外壳说明
└── installer/
    └── setup.bat                # 🪟  Windows 一键安装
```

---

## 🎯 核心功能

### 🔒 安全监控
- ✅ Windows 防火墙状态实时检查
- ✅ Windows Defender 运行状态
- ✅ 安全事件日志分析 (登录失败/权限变更等)
- ✅ 防火墙阻止规则统计

### 🌐 网络保护
- ✅ 所有活跃网络连接监控
- ✅ 可疑端口检测 (Meterpreter/C2/后门)
- ✅ 恶意 IP 段识别
- ✅ 高频连接异常告警

### ⚙️ 进程检查
- ✅ 已知黑客工具特征检测
- ✅ CPU/内存异常占用告警
- ✅ 新进程出现追踪
- ✅ 支持一键终止可疑进程

### 🤖 AI 状态
- ✅ 实时显示 AI 助手工作状态
- ✅ 工作进度条
- ✅ 当前任务描述
- ✅ 支持主动上报状态

### 📊 Web Dashboard
- ✅ 浏览器实时查看 (http://127.0.0.1:5000)
- ✅ 精美深色 UI
- ✅ 安全等级可视化
- ✅ 威胁详情列表
- ✅ 系统资源监控

### 🖥️ 系统托盘
- ✅ 任务栏图标
- ✅ 状态色变化 (绿/黄/红)
- ✅ 右键菜单快捷操作
- ✅ 最小化到托盘

---

## ⚙️ 配置说明

编辑 `pc_agent/config.yaml`:

```yaml
device:
  mode: auto          # serial | wifi | auto | none
  serial:
    port: auto        # COM端口, auto=自动检测
    baudrate: 115200

security:
  scan_interval: 5    # 扫描间隔(秒)
  network:
    suspicious_ports: [4444, 1337, 31337, ...]
  process:
    suspicious_names: ["mimikatz", "nmap", ...]
    cpu_threshold: 80
    mem_threshold: 80

dashboard:
  enabled: true
  port: 5000

system_tray:
  enabled: true
```

---

## 🔌 通信协议

PC Agent 与 ESP32 通过 JSON over Serial 通信:

**状态更新:**
```json
{
  "cmd": "update",
  "ai_status": "working",
  "sec_level": "safe",
  "threat_count": 0,
  "active_connections": 42,
  "firewall_on": true,
  "cpu_usage": 23.5,
  "messages": ["一切正常"]
}
```

**紧急告警:**
```json
{
  "cmd": "alert",
  "message": "检测到可疑连接: 192.168.1.100:4444"
}
```

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 嵌入式设备 | ESP32 + Arduino C++ |
| 显示驱动 | Adafruit SSD1306 + GFX |
| 通信协议 | JSON over Serial / WiFi TCP |
| PC Agent | Python 3.10+ |
| 系统监控 | psutil, pywin32, WMI |
| 网络分析 | scapy, python-nmap |
| Web 仪表盘 | Flask + 原生 JS |
| 系统托盘 | pystray + Pillow |

---

## 🐛 故障排除

### 设备未连接
1. 检查 USB 线是否支持数据传输 (不是纯充电线)
2. 检查设备管理器中的 COM 端口号
3. 尝试手动指定端口: `config.yaml` → `device.serial.port: COM3`

### OLED 不显示
1. 检查接线: VCC 必须接 **3.3V** (不是 5V!)
2. 检查 I2C 地址: 默认 0x3C，部分模块是 0x3D
3. 修改 `firmware.ino` 中的 `OLED_ADDR`

### 部分功能不可用
- pywin32 需要 Windows 且需要管理员权限
- 安全事件日志读取需要管理员权限
- 某些防火墙操作需要管理员权限

---

## 📜 许可证

MIT License - 自由使用、修改、分发

---

## 🙏 致谢

- ESP32 & Arduino 社区
- Adafruit SSD1306 库
- psutil 项目
- Flask 框架

---

**🛡️ 保护你的数字世界，从一个微小的设备开始。**
