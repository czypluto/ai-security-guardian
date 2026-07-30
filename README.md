# 🛡️ AI 网络安全管家

> **嵌入式硬件 + 桌面安全监控 + AI Agent + 纵深防御 四位一体的开源安全守护系统**
>
> ESP32 物理终端实时显示安全状态 · ReAct AI Agent 智能分析威胁 · 运行时自审计防篡改
> 下载前置扫描 + 网络隔离 + Windows 防火墙 · 全部零件淘宝可买，成本仅 ¥33-100

<p align="center">
  <img src="https://img.shields.io/badge/version-3.3-blue" alt="version">
  <img src="https://img.shields.io/badge/python-3.10+-green" alt="python">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey" alt="platform">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="license">
  <img src="https://img.shields.io/badge/ESP32-Arduino-blue" alt="esp32">
</p>

---

## 📸 效果预览

### ESP32 物理终端

设备外接 0.96" OLED 显示屏，通过"安小盾"二次元角色展示安全状态：

```
┌──────────────────────┐       ┌──────────────────────┐
│ ▂▃▄▅ ●           SAFE│       │ ▂▃▄▅     DANGER│
│────────────────────│       │══════════════════════│
│                      │       │                      │
│   (･ω･)              │       │   (>_<)              │
│   安小盾 守护中...    │       │   检测到威胁!        │
│                      │       │                      │
│   FW:ON  AV:ON       │       │   ⚠ DANGER ⚠        │
│   连接: 42  威胁: 0   │       │   威胁: 3  连接: 55  │
└──────────────────────┘       └──────────────────────┘
   安全模式 (表情屏)              危险模式 
```

### PyQt5 桌面 GUI

极简暗色主题桌面应用，实时安全概览 + AI 对话窗口。

### Web Dashboard

浏览器访问 `http://127.0.0.1:5000`，深色实时安全面板。

### CLI Agent

```bash
$ python agent_cli.py "全面扫描我的网络安全"

  [tool] scan_network()
  → 42 个活跃连接, 0 个可疑 IP
  [tool] scan_processes()
  → 0 个可疑进程
  [tool] check_firewall()
  → 防火墙: 开启 | Defender: 开启

🛡️ 系统状态: 安全
当前没有发现活跃威胁。防火墙和 Defender 均正常运行。
网络连接数正常，无可疑进程。
```

---

## 🏗️ 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     你的电脑 (Windows)                         │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              PC Agent — 安全监控引擎                     │  │
│  │                                                        │  │
│  │  Network       Process       Firewall      Security    │  │
│  │  Monitor       Monitor       Checker       Monitor     │  │
│  │  (psutil)      (psutil)      (netsh+PS)    (EventLog)  │  │
│  │     │              │             │             │       │  │
│  │     └──────────────┼─────────────┼─────────────┘       │  │
│  │                    ▼             ▼                      │  │
│  │              GuardianController                         │  │
│  │           (状态管理 + 安全等级计算)                       │  │
│  │     │           │            │            │             │  │
│  │     ▼           ▼            ▼            ▼             │  │
│  │  Device    Character      LLM          Web             │  │
│  │  Bridge    Manager        Client       Dashboard       │  │
│  │  (Serial   (安小盾角色     (DeepSeek/   (Flask          │  │
│  │   /WiFi)   表情+台词)      智谱/硅基)    :5000)          │  │
│  │     │                                         │        │  │
│  └─────┼─────────────────────────────────────────┘        │  │
│        │ USB Serial                                        │  │
│        ▼                                                   │  │
│  ┌──────────────────────────┐                              │  │
│  │   ESP32 + OLED/TFT        │                              │  │
│  │   角色动画 + 安全仪表盘    │                              │  │
│  └──────────────────────────┘                              │  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              AI Agent — ReAct 智能大脑                   │  │
│  │                                                        │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │  │
│  │  │ ReAct    │  │ MCP      │  │ Skill    │             │  │
│  │  │ Core     │  │ Client   │  │ Manager  │             │  │
│  │  │ Think→   │  │ (JSON-   │  │ (.md     │             │  │
│  │  │ Act→     │  │  RPC)    │  │ 文件)    │             │  │
│  │  │ Observe  │  │          │  │          │             │  │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘             │  │
│  │       └──────────────┼────────────┘                    │  │
│  │                      ▼                                  │  │
│  │              Tool Registry (20+ 工具)                    │  │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │  │
│  │  │Security │ │Defender  │ │OTX Threat│ │NVD CVE    │  │  │
│  │  │Sandbox  │ │Scanner   │ │Intel     │ │Lookup     │  │  │
│  │  │(6层隔离) │ │(PS CMD)  │ │(免费API) │ │(免费API)  │  │  │
│  │  └─────────┘ └──────────┘ └──────────┘ └───────────┘  │  │
│  │                                                        │  │
│  │  Knowledge Base (ChromaDB + 向量检索)                   │  │
│  │  MCP Server Mode (暴露工具给 Claude Code 等)            │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 🎯 核心功能

### 🔒 安全监控 (PC Agent)
- ✅ **网络监控** — 活跃连接、可疑 IP 段识别、C2/后门端口检测 (20+ 恶意端口库)
- ✅ **进程监控** — 黑客工具特征检测 (20+ 黑名单)、CPU/内存异常告警、一键终止
- ✅ **防火墙检查** — netsh + PowerShell 多级降级策略、30s 缓存防抖
- ✅ **安全事件** — Windows EventLog 分析 (18 种可疑 EventID)
- ✅ **Defender 状态** — 实时杀毒状态 + 快速/全盘扫描

### 🤖 AI Agent (ReAct 智能大脑)
- ✅ **ReAct 循环** — Think → Act → Observe，最多 10 轮迭代
- ✅ **多模型支持** — DeepSeek / 智谱 AI / 硅基流动，自动故障转移
- ✅ **30+ 内置工具** — 安全扫描、威胁情报、CVE 查询、命令沙箱、自审计、ESP32 隔离、下载扫描
- ✅ **流式输出** — CLI 模式下 LLM 回复逐字显示
- ✅ **CLI 对话模式** — `/tools` `/save` `/kb` `/run` 等斜杠命令

### 🌐 威胁情报
- ✅ **AlienVault OTX** — IP/域名/文件哈希信誉查询 (免费 API，5 分钟缓存)
- ✅ **NIST NVD** — CVE 漏洞查询与关键词搜索 (免费 US 政府 API)
- ✅ **DuckDuckGo** — 无追踪安全搜索 + 网页抓取

### 📟 ESP32 硬件终端
- ✅ **双屏设计** — 表情屏 (颜文字角色) + 仪表盘 (安全数据)，按键/指令切换
- ✅ **角色引擎** — "安小盾" 二次元角色，8 种表情 + 60+ 句台词
- ✅ **告警系统** — 威胁时 OLED 双线边框 + RGB LED 红灯 + 蜂鸣器
- ✅ **双通信** — USB Serial (自动检测 COM 口) + WiFi TCP
- ✅ **双硬件** — 0.96" OLED (SSD1306) + TTGO T-Display (TFT 彩屏)

### 🔌 MCP 协议 (Model Context Protocol)
- ✅ **MCP Client** — 连接外部 MCP Server，自动发现工具 (stdio + HTTP)
- ✅ **MCP Server** — 将 Guardian 安全工具暴露给 Claude Code 等外部客户端
- ✅ **JSON-RPC 2.0** — 符合 MCP 2024-11-05 规范

### 📦 Skills 技能系统
- ✅ **拖放安装** — `.md` 文件放入 `skills/` 目录自动加载
- ✅ **触发匹配** — 用户输入匹配技能触发词，自动注入系统提示词
- ✅ **4 个内置技能** — 全面审计、网络扫描、进程检查、勒索软件检测
- ✅ **用户自定义** — `skills/user/` 目录支持个人技能

### 🧠 知识库系统
- ✅ **ChromaDB 向量存储** — 对话自动保存，语义检索历史上下文
- ✅ **双模 Embedding** — MiniLM 生产模式 + TF-IDF 零依赖后备
- ✅ **越用越聪明** — 每次对话自动积累，检索结果注入新对话

### 🔒 安全沙箱
- ✅ **6 层隔离** — 命令白名单 (19+) → Job Object → Restricted Token → 资源限制 → 文件守卫 → 审计日志
- ✅ **fail-closed** — 任一层失败，默认拒绝执行

### 🛡️ 运行时自审计 (v3.3 新增)
- ✅ **启动自检** — 每次启动自动验证代码完整性，被篡改立即告警
- ✅ **7 层审计** — 文件哈希 → 依赖审计 → 配置守卫 → 运行时完整性 → 代码注入扫描 → 网络自查 → 沙箱测试
- ✅ **完整性清单** — SHA256 哈希基线，`git pull` 后一键更新
- ✅ **0-100 评分** — 综合安全评分，严重问题熔断告警

### 🔌 ESP32 网络隔离 (v3.3 新增)
- ✅ **Serial 纯显示** — 默认仅 USB Serial 通信，ESP32 无法触网
- ✅ **命令白名单** — 6 种合法指令，连续 10 次非法即熔断
- ✅ **速率限制** — 每秒最多 20 条，防串口洪泛攻击
- ✅ **外泄防护** — ESP32 回传数据不得离开本机
- ✅ **Windows 防火墙** — 内核级封锁 C2 端口 (4444/31337/6666 等)
- ✅ **固件指纹** — 启动握手验证，检测固件替换

### 🔍 下载前置扫描 (v3.3 新增)
- ✅ **Skill 安装前扫描** — 提示注入、隐藏 Unicode、代码执行模式检测
- ✅ **MCP 推荐前扫描** — 危险 flag、typosquatting 仿冒检测
- ✅ **curl|bash 拦截** — #1 攻击向量直接拒绝
- ✅ **Claude Code Hook** — Write/Bash 操作自动触发扫描

### 💻 用户界面 (4 种)
| 界面 | 启动方式 | 说明 |
|------|----------|------|
| CLI 命令行 | `python main.py` | 彩色日志，适合服务器/后台 |
| PyQt5 桌面 GUI | `python main.py --gui` | 暗色极简主题，状态卡片 |
| AI 对话窗口 | GUI 内打开 | 流式对话，快速操作按钮 |
| 系统托盘 | 自动 (GUI 内置) | 状态色图标，最小化到托盘 |

---

## 🚀 快速开始

### 1. 硬件准备 (可选)

如果你想要物理终端，参见 **[📦 淘宝零件清单](docs/parts_list.md)**。

**最简单的入门方案 (¥33):**
- ESP32 开发板 ×1 (¥15)
- 0.96" OLED 屏 ×1 (¥10)
- 杜邦线 母对母 ×4 (¥3)
- USB 数据线 ×1 (¥5)

**接线 (4 根线):**
```
OLED GND → ESP32 GND
OLED VCC → ESP32 3.3V
OLED SCL → ESP32 D22
OLED SDA → ESP32 D21
```

参见 **[🔧 组装指南](docs/assembly_guide.md)**。

### 2. 烧录固件

1. 安装 [Arduino IDE](https://www.arduino.cc/en/software)
2. 安装 ESP32 开发板支持
3. 安装 `Adafruit SSD1306`、`Adafruit GFX` 和 `ArduinoJson` 库
4. 打开 `firmware/firmware.ino`，点击上传

> 💡 如果你有 **TTGO T-Display** (推荐，约 ¥55)，使用 `firmware/firmware_tdisplay/firmware_tdisplay.ino` 可获得彩色 TFT 显示。

### 3. 安装 PC 端

```bash
# 克隆项目
git clone https://github.com/czypluto/ai-security-guardian.git
cd ai-security-guardian

# 创建虚拟环境 (推荐)
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r pc_agent/requirements.txt

# 可选: 安装知识库支持
pip install chromadb sentence-transformers
```

或直接运行 `installer/setup.bat` 一键安装。

### 4. 配置 LLM API Key

编辑 `pc_agent/config.yaml` 或设置环境变量：

```bash
# 推荐: DeepSeek
set DEEPSEEK_API_KEY=sk-your-key


```

> 💡 不配置 API Key 也可运行 — 角色将使用本地台词库，Agent CLI 功能受限。

参见 **[🤖 LLM 配置指南](docs/llm_setup_guide.md)** 获取详细说明。

### 5. 启动!

```bash
# 桌面 GUI 模式 (推荐)
python pc_agent/main.py --gui

# 或者 CLI 模式
python pc_agent/main.py


# AI Agent 对话模式
python agent_cli.py --chat

# AI Agent 单次执行
python agent_cli.py "扫描我的网络安全"
```

或双击 `start_guardian.bat` 一键启动。

### 6. 安全基线 (首次运行必做)

```bash
# 生成完整性基线 (记录所有文件的 SHA256 哈希)
python generate_integrity_manifest.py

# 运行完整自审计 (验证系统未被篡改)
python agent/self_audit.py --full

# ESP32 网络隔离审计
python agent/esp32_isolation.py --audit

# 安装 Windows 防火墙规则 (需管理员)
powershell -File firewall_isolation.ps1
```

---

## 📂 项目结构

```
ai-security-guardian/
├── README.md                          # 本文件
├── PROJECT_FULL_STORY.md              # 项目全纪实 (推荐阅读)
├── agent_cli.py                       # AI Agent CLI 入口
├── start_guardian.bat                 # Windows 一键启动
├── requirements-lock.txt              # 锁定依赖版本
│
├── pc_agent/                          # 💻 PC 端安全引擎
│   ├── main.py                        #   主入口 GuardianController
│   ├── config.yaml                    #   全局配置
│   ├── requirements.txt               #   Python 依赖
│   ├── device_bridge.py               #   设备通信 (Serial/WiFi)
│   ├── security_monitor.py            #   安全事件监控 (EventLog)
│   ├── network_monitor.py             #   网络威胁检测
│   ├── process_monitor.py             #   可疑进程检测
│   ├── firewall_checker.py            #   防火墙/Defender 检查
│   ├── character_manager.py           #   角色表情+台词管理
│   ├── llm_client.py                  #   多模型 LLM 客户端
│   ├── web_dashboard.py               #   Flask Web 仪表盘
│   ├── desktop_gui.py                 #   PyQt5 桌面 GUI
│   ├── chat_window.py                 #   AI 对话窗口
│   ├── system_tray.py                 #   系统托盘
│   └── ai_status.py                   #   AI 状态追踪
│
├── agent/                             # 🧠 AI Agent 子系统
│   ├── core.py                        #   ReAct Agent 核心循环
│   ├── config.py                      #   Agent 配置 + 系统提示词
│   ├── llm.py                         #   LLM 路由器 (function calling)
│   ├── tools.py                       #   工具注册表 + 30+ 内置工具
│   ├── mcp_client.py                  #   MCP JSON-RPC 客户端
│   ├── mcp_server_mode.py             #   MCP Server 模式 (供外部调用)
│   ├── sandbox.py                     #   6 层安全沙箱
│   ├── self_audit.py                  #   运行时自审计引擎 (v3.3)
│   ├── esp32_isolation.py             #   ESP32 网络隔离守护 (v3.3)
│   ├── download_scanner.py            #   下载前置安全扫描 (v3.3)
│   ├── skill_loader.py                #   .md 技能自动加载
│   ├── knowledge_base.py              #   向量知识库 (ChromaDB)
│   ├── defender_tools.py              #   Defender + NVD CVE
│   ├── otx_tools.py                   #   AlienVault OTX 威胁情报
│   ├── web_tools.py                   #   DuckDuckGo 搜索 + 抓取
│   └── installer.py                   #   技能安装 + MCP 推荐 (含扫描)
│
├── firmware/                          # 🔌 ESP32 固件
│   ├── character_engine.h             #   角色动画引擎
│   ├── firmware_tdisplay/             #   T-Display TFT 彩色固件
│   └── oled_test/                     #   OLED I2C 诊断工具
│
├── skills/                            # 📦 Agent 技能文件
│   ├── full_audit.md                  #   全面安全审计
│   ├── network_scan.md                #   网络扫描分析
│   ├── process_check.md               #   进程行为检查
│   ├── ransomware_check.md            #   勒索软件检测
│   ├── self_audit.md                  #   自审计触发规则 (v3.3)
│   ├── download_safety.md             #   下载前置扫描规则 (v3.3)
│   └── user/                          #   用户自定义技能
│
├── tests/                             # 🧪 单元测试
│   ├── conftest.py                    #   共享 fixtures + mock
│   ├── test_controller.py             #   GuardianController 测试
│   ├── test_firewall_checker.py       #   FirewallChecker 测试
│   ├── test_network_monitor.py        #   NetworkMonitor 测试
│   ├── test_character_manager.py      #   CharacterManager 测试
│   └── test_device_bridge.py          #   DeviceBridge 测试
│
├── tools/                             # 🔧 辅助工具
│   ├── image_to_character.py          #   PNG → C header 角色转换
│   └── generate_report.py             #   安全报告生成
│
├── knowledge_base/                    # 🧠 本地知识库
│   ├── conversations/                 #   Markdown 对话文件
│   └── chroma/                        #   ChromaDB 向量数据
│
├── docs/                              # 📖 文档
│   ├── parts_list.md                  #   淘宝零件清单
│   ├── assembly_guide.md              #   硬件组装指南
│   └── llm_setup_guide.md             #   LLM API 配置指南
│
├── enclosure/                         # 🖨️ 3D 外壳
│   └── case_design.md                 #   外壳设计说明
│
├── installer/                         # 🪟 安装程序
│   └── setup.bat                      #   Windows 一键安装
│
└── dify_designs/                      # 🎨 Dify 提示词设计
    ├── README.md
    └── system_prompt.md
```

---

## 🔌 通信协议

PC Agent 与 ESP32 通过 JSON over Serial (115200bps) 通信：

**状态更新:**
```json
{
  "cmd": "update",
  "sec_level": "safe",
  "threat_count": 0,
  "active_connections": 42,
  "suspicious_ips": 0,
  "firewall_on": true,
  "defender_on": true,
  "cpu_usage": 23.5,
  "mem_usage": 45.2,
  "messages": ["一切正常"]
}
```

**紧急告警:**
```json
{"cmd": "alert", "message": "检测到可疑连接: 192.168.1.100:4444"}
```

**角色指令:**
```json
{"cmd": "expression", "expression": 4}
{"cmd": "say", "text": "主人! 防火墙怎么关了!"}
{"cmd": "screen", "screen": 1}
```

---

## ⚙️ 配置说明

编辑 `pc_agent/config.yaml`：

```yaml
# 设备连接
device:
  mode: serial         # serial (推荐, 网络隔离) | wifi | none
  serial:
    port: auto
    baudrate: 115200

# 安全监控
security:
  scan_interval: 5    # 扫描间隔(秒)
  network:
    suspicious_ports: [4444, 1337, 31337, 6666, 6667, 8080, 8888, 9001]
  process:
    suspicious_names: ["nmap", "mimikatz", "metasploit", "cobalt", ...]
    cpu_threshold: 80
    mem_threshold: 80

# 大模型 API
llm:
  enabled: true
  default_model: "deepseek-v4-pro"
  deepseek:
    enabled: true
    api_key: "${DEEPSEEK_API_KEY}"

# MCP 服务器 (扩展工具, 安装前自动安全扫描)
mcp_servers: []

# 知识库
knowledge_base:
  enabled: true
  top_k: 3
```

---

## 🛠️ 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| **嵌入式** | Arduino C++ / ESP32 | 固件开发 |
| **显示驱动** | Adafruit SSD1306 + GFX / TFT_eSPI | OLED / TFT |
| **通信协议** | JSON over Serial (115200bps) / WiFi TCP | PC ↔ ESP32 |
| **PC Agent** | Python 3.10+ | 主控程序 |
| **系统监控** | psutil, pywin32, WMI | 进程/网络/事件日志 |
| **LLM** | OpenAI-compatible API | DeepSeek / 智谱 / 硅基流动 |
| **桌面 GUI** | PyQt5 + QSS | 暗色极简主题 |
| **Web 仪表盘** | Flask + 原生 JS | 实时面板 |
| **系统托盘** | pystray + Pillow | 后台运行 |
| **向量数据库** | ChromaDB | 对话语义检索 |
| **Embedding** | sentence-transformers (MiniLM) / TF-IDF 后备 | 双模 |
| **MCP 协议** | JSON-RPC 2.0 | 工具扩展 |
| **威胁情报** | AlienVault OTX + NIST NVD | 免费 API |
| **搜索** | DuckDuckGo Lite | 免费无 Key |
| **安全沙箱** | Job Object + Restricted Token + 白名单 | 6 层隔离 |
| **自审计** | SHA256 哈希 + 依赖扫描 + 代码注入检测 | 启动时自动运行 |
| **网络隔离** | 串口白名单 + 防火墙 C2 封锁 + 外泄防护 | ESP32 零网络暴露 |
| **前置扫描** | Regex 模式库 + Unicode 隐藏检测 + Typo 检测 | 安装前自动拦截 |
| **Claude Code** | PreToolUse Hook | Write/Bash 操作自动安检 |
| **测试** | pytest + unittest.mock | 单元测试 |

---

## 🤝 MCP 集成

Guardian 实现了完整的 MCP (Model Context Protocol) 支持，可以与其他 AI 工具互操作：

### 作为 MCP Client (调用外部工具)

```yaml
# config.yaml
mcp_servers:
  - name: my-tools
    transport: stdio
    command: "python -m my_mcp_server"
  - name: remote-api
    transport: http
    url: "http://localhost:9000/mcp"
```

### 作为 MCP Server (被外部调用)

```bash
# 将 Guardian 的安全工具暴露给 Claude Code 等外部客户端
python -m agent.mcp_server_mode
```

在 Claude Code 中配置：
```json
{
  "mcpServers": {
    "guardian": {
      "command": "python",
      "args": ["-m", "agent.mcp_server_mode"],
      "cwd": "/path/to/ai-security-guardian"
    }
  }
}
```

---

## 🧪 运行测试

```bash
pytest tests/ -v
```

---

## 🐛 故障排除

### ESP32 未连接
1. 检查 USB 线是否支持数据传输 (不是纯充电线)
2. 检查设备管理器中的 COM 端口号
3. 手动指定端口: `config.yaml` → `device.serial.port: COM3`

### OLED 不显示
1. 检查接线: VCC 必须接 **3.3V** (不是 5V!)
2. 检查 I2C 地址: 默认 `0x3C`，部分模块是 `0x3D` → 修改 `firmware.ino` 中的 `OLED_ADDR`
3. 运行 `firmware/oled_test/oled_test.ino` 诊断 I2C 连接

### LLM 调用失败
1. 检查 API Key 是否正确设置
2. 检查网络是否能访问对应 API 端点
3. 查看 `guardian.log` 获取详细错误信息
4. 不配置 LLM 也可使用基础监控功能

### 部分功能不可用
- 需要 **管理员权限** 运行: 安全事件日志、Defender 详细信息、进程终止
- 右键启动程序 → "以管理员身份运行"

---

---

## 🛡️ 纵深防御体系 (v3.3)

```
外部攻击面
    │
    ▼
┌─────────────────────────────────────────────┐
│ 第 0 层: 下载前置扫描                         │
│   Claude Code Hook → download_scanner       │
│   拦截: 提示注入 / 隐藏 Unicode / curl|bash  │
├─────────────────────────────────────────────┤
│ 第 1 层: 启动自审计                           │
│   GuardianController → quick_check (~1s)    │
│   验证: 文件哈希 / 依赖 / 配置 / 运行时       │
├─────────────────────────────────────────────┤
│ 第 2 层: ESP32 网络隔离                       │
│   DeviceBridge → cmd_validator + egress_grd │
│   Windows Firewall → C2 端口内核级封锁       │
├─────────────────────────────────────────────┤
│ 第 3 层: 6 层安全沙箱                         │
│   白名单 → Job Object → Token → 资源 → 文件   │
├─────────────────────────────────────────────┤
│ 第 4 层: AI Agent 守则                        │
│   系统提示词约束 + Skill 触发匹配 + 25 工具   │
├─────────────────────────────────────────────┤
│ 第 5 层: 事后审计                             │
│   self_audit --full (7 项, ~3s)             │
│   定期验证 + 异常熔断                          │
└─────────────────────────────────────────────┘
```

---

## 🗺️ 路线图

- [x] 运行时自审计 (v3.3) — 7 层完整性验证
- [x] ESP32 网络隔离 (v3.3) — 纯显示外设, 零网络暴露
- [x] 下载前置扫描 (v3.3) — Skill/MCP/插件安装前自动安检
- [ ] 角色自定义编辑器 (GUI)
- [ ] Linux/macOS 跨平台支持
- [ ] 移动端 App (查看远程安全状态)
- [ ] 社区技能市场

---

## 📜 许可证

MIT License — 自由使用、修改、分发

---

## 🙏 致谢

- ESP32 & Arduino 社区
- Adafruit SSD1306 / GFX 驱动库
- psutil 系统监控库
- ChromaDB 向量数据库
- AlienVault OTX 免费威胁情报
- NIST NVD 免费漏洞数据库
- PyQt5 桌面框架
- 智谱 AI、DeepSeek、硅基流动

---

**🛡️ 保护你的数字世界，从一个微小的设备开始。**

> *"安全不该是冷冰冰的警告弹窗，而是一个有温度的伙伴。"* — 安小盾
