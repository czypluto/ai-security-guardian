# 🛡️ AI 网络安全管家 — 项目全纪实

> **作者**: Chen Ziye (陈梓烨)
> **日期**: 2026-07-29
> **版本**: v3.2
> **定位**: 嵌入式 + 桌面端 + AI Agent 三位一体的开源网络安全守护系统

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [PC Agent 层 — 安全监控引擎](#3-pc-agent-层--安全监控引擎)
4. [AI Agent 层 — ReAct 智能大脑](#4-ai-agent-层--react-智能大脑)
5. [ESP32 固件层 — 硬件终端](#5-esp32-固件层--硬件终端)
6. [用户界面层](#6-用户界面层)
7. [知识库系统 — 向量化对话记忆](#7-知识库系统--向量化对话记忆)
8. [Skills 技能系统](#8-skills-技能系统)
9. [MCP 协议支持](#9-mcp-协议支持)
10. [安全沙箱设计](#10-安全沙箱设计)
11. [遇到的关键问题与解决方案](#11-遇到的关键问题与解决方案)
12. [技术栈总览](#12-技术栈总览)
13. [项目文件清单](#13-项目文件清单)

---

## 1. 项目概述

### 1.1 这是什么

**AI 网络安全管家** 是一个集成了 **ESP32 嵌入式硬件**、**Windows 桌面安全监控**、**大模型 AI Agent** 的完整开源系统。它可以：

- 🖥️ **实时监控** Windows 系统安全状态（网络连接、进程行为、防火墙、Defender）
- 🤖 **AI 驱动分析** — DeepSeek v4 pro 大模型，25 个安全工具可通过 function calling 调用
- 📟 **物理终端** — ESP32 + OLED 屏幕，显示颜文字角色"安小盾"的表情和台词
- 💬 **桌面 GUI** — PyQt5 暗色极简主题，实时仪表盘 + AI 对话窗口（支持工具调用可视化）
- 🧠 **向量知识库** — ChromaDB + TF-IDF 后备，自动保存对话并支持语义检索
- 🔌 **MCP 协议** — 既可作为 Client 连接外部工具，也可作为 Server 暴露自身能力
- 📦 **Skills 技能系统** — 拖放 .md 文件即可扩展 Agent 能力
- 🔒 **多层安全沙箱** — 命令白名单 + Job Object + Restricted Token + 审计日志

### 1.2 设计哲学

传统安全软件（360、腾讯管家等）的问题是：**闭源不透明、过度商业化、交互生硬**。

这个项目的目标是做一个**开源、透明、有温度**的安全守护系统：
- 通过"安小盾"让安全监控变得有趣
- 通过大模型让安全分析变得智能
- 通过本地向量知识库实现越用越聪明
- 通过 MCP 协议实现能力无限扩展
- AI 可以主动调用工具获取实时数据，而非凭空猜测

### 1.3 硬件成本

| 方案 | 组件 | 价格 |
|---|---|---|
| 基础版 | ESP32 + 0.96" OLED + 面包板 + 杜邦线 | ~33 RMB |
| 推荐版 | TTGO T-Display (集成彩屏) | ~55 RMB |
| 豪华版 | ESP32 + 彩屏 + 电池 + LED + 蜂鸣器 + 3D 外壳 | ~100 RMB |

---

## 2. 整体架构

```
                          ┌──────────────────────────────────────────────────┐
                          │                PC Agent (Python 3.10+)             │
                          │                                                   │
    ESP32 Hardware        │  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
    ┌──────────────┐      │  │ Network  │  │ Process  │  │  Firewall     │  │
    │ OLED/TFT     │      │  │ Monitor  │  │ Monitor  │  │  Checker      │  │
    │ 128×64       │◄─────┤  │(psutil)  │  │(psutil)  │  │(netsh+PS)     │  │
    │ Kaomoji      │ JSON │  └────┬─────┘  └────┬─────┘  └──────┬────────┘  │
    │ Emoji        │Serial│       └─────────┬──┴───────────────┘            │
    │ Buzzer+LED   │      │                 ▼                               │
    └──────────────┘      │  ┌──────────────────────────────────────────┐   │
                          │  │        GuardianController                 │   │
                          │  │  (状态管理 + 安全等级计算 + 扫描循环)       │   │
                          │  └────────────┬─────────────────────────────┘   │
                          │               │                                  │
                          │  ┌────────────┼────────────┐                    │
                          │  ▼            ▼            ▼                    │
                          │ Device    Character    LLM Adapter              │
                          │ Bridge    Manager    (MultiLLMClient)           │
                          │ (Serial/  (表情+台词  ┌── 封装 ──┐              │
                          │  WiFi)    +LLM台词)   │ agent/llm.py            │
                          │                       │ LLMRouter              │
                          │                       │ (DeepSeek v4 pro)       │
                          │                       └──────────┘              │
                          │                                     │           │
                          │  ┌──────────────────────────────────┤           │
                          │  ▼              ▼                   ▼           │
                          │ Desktop GUI   System Tray      AI Chat Window   │
                          │ (PyQt5)       (pystray)        (ReAct+Tools)    │
                          │                                                   │
                          │  ┌──────────────────────────────────────────┐   │
                          │  │            AI Agent 层                     │   │
                          │  │  ┌────────┐  ┌────────┐  ┌────────────┐  │   │
                          │  │  │ReAct   │  │MCP     │  │Skill       │  │   │
                          │  │  │Core    │  │Client  │  │Manager     │  │   │
                          │  │  └───┬────┘  └───┬────┘  └─────┬──────┘  │   │
                          │  │      │           │             │          │   │
                          │  │  ┌───┴───────────┴─────────────┴──────┐   │   │
                          │  │  │         Tool Registry (25 tools)   │   │   │
                          │  │  └───────────────┬───────────────────┘   │   │
                          │  │                  │                       │   │
                          │  │  ┌───────────────┼───────────────────┐   │   │
                          │  │  ▼               ▼                   ▼   │   │
                          │  │ Security      Defender    OTX Threat    │   │
                          │  │ Sandbox       Scanner     Intel         │   │
                          │  │ (命令白名单    (PS CMD)    (AlienVault)  │   │
                          │  │  +JobObject)                            │   │
                          │  └──────────────────────────────────────────┘   │
                          │                                                   │
                          │  ┌──────────────────────────────────────────┐   │
                          │  │         Knowledge Base                    │   │
                          │  │  ChromaDB + sentence-transformers         │   │
                          │  │  (TF-IDF fallback when no torch)          │   │
                          │  └──────────────────────────────────────────┘   │
                          └──────────────────────────────────────────────────┘
```

### 2.1 数据流

```
Windows 系统 API (psutil / WMI / netsh / PowerShell)
        │
        ▼
安全监控模块 (Network/Process/Firewall/Security)
        │
        ▼
GuardianController (统一状态字典 state: dict)
        │
        ├──► DeviceBridge ──► ESP32 OLED (安全仪表盘 + 颜文字表情)
        ├──► Desktop GUI ──► PyQt5 桌面窗口 (状态卡片 + AI 对话)
        ├──► System Tray ──► 任务栏图标 + 右键菜单 (CLI 模式)
        ├──► CharacterManager ──► LLM 动态台词 or 本地库兜底
        └──► AI Agent (ReAct loop) ──► 工具调用 ──► 结果返回
```

---

## 3. PC Agent 层 — 安全监控引擎

### 3.1 主控制器 `main.py` — `GuardianController`

**职责**: 整个 PC Agent 的中央调度器。

```python
class GuardianController:
    def __init__(self):
        self.state = {           # 全局状态字典 (推送到 ESP32)
            'sec_level': 'safe',    # 安全等级: safe/warning/danger
            'threat_count': 0,      # 活跃威胁数
            'active_connections': 0, # 活跃连接数
            'suspicious_ips': 0,    # 可疑 IP 数
            'firewall_on': True,    # 防火墙状态
            'defender_on': True,    # Defender 状态
            'cpu_usage': 0,        # CPU 使用率
            'mem_usage': 0,        # 内存使用率
            'messages': [],        # 最近事件消息 (最多5条)
        }
```

**启动参数**:

| 参数 | 说明 |
|---|---|
| `python main.py` | CLI 模式 (默认) |
| `python main.py --gui` | PyQt5 桌面 GUI 模式 |
| `python main.py --no-device` | 不连接 ESP32 |
| `python main.py --no-tray` | 禁用系统托盘 |

### 3.2 网络监控 `network_monitor.py`

- **技术**: `psutil.net_connections(kind='inet')`
- **恶意端口库**: 20+ 常见 C2/后门端口 (4444 Metasploit, 31337 Back Orifice, 6666 IRC C2 等)
- **高频连接检测**: 同 IP 短时间 >50 次连接标为可疑
- **监听端口收集**: `get_listening_ports()` → 供漏洞检查模块使用

### 3.3 进程监控 `process_monitor.py`

- **技术**: `psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'exe', 'cmdline'])`
- **黑名单**: 20+ 黑客工具特征 (mimikatz, nmap, metasploit, cobalt strike, wireshark, hashcat 等)
- **异常检测**: CPU >80% 告警

### 3.4 防火墙检查 `firewall_checker.py`

- **多级降级策略**:
  1. `netsh advfirewall show allprofiles state` (最快)
  2. PowerShell `Get-NetFirewallProfile` (备选)
  3. `sc query mpssvc` 服务检查 (兜底)
- **Defender 检测**: PowerShell `Get-MpComputerStatus` → psutil MsMpEng.exe → `sc query WinDefend`
- **编码修复**: 所有 `subprocess.run()` 显式 `encoding="utf-8", errors="replace"`
- **缓存机制**: 30 秒检查间隔，连续失败用缓存兜底

### 3.5 安全事件监控 `security_monitor.py`

- **Windows 安全日志**: 通过 `win32evtlog` 读取 Security 日志 (18 种可疑 EventID)
- **摘要统计**: 失败登录数、新进程数、新用户数、风险等级

### 3.6 设备通信桥 `device_bridge.py`

- **双模通信**: Serial (USB) + WiFi (TCP Socket)
- **自动检测**: 扫描 COM 口识别 CP210x/CH340 等 ESP32 常见芯片
- **心跳保活**: 每 2 秒 ping/pong
- **断连恢复**: 防重入锁保护，重新连接前先关闭旧端口

```json
{"cmd": "update", "sec_level": "safe", "threat_count": 0, ...}
{"cmd": "alert", "message": "检测到可疑连接: 192.168.1.100:4444"}
{"cmd": "expression", "expression": 4}
{"cmd": "say", "text": "主人! 防火墙怎么关了!"}
{"cmd": "screen", "screen": 1}
```

### 3.7 角色管理器 `character_manager.py`

- **表情系统**: 7 种表情 (idle/happy/working/worried/angry/sleep/greeting)
- **本地台词库**: 12 个类别 60+ 句预设台词，避免重复
- **LLM 动态生成**: 调用 LLM 实时生成角色台词
- **LLM 降级策略**: 连续失败 5 次 → 冷却 30 秒，自动切回本地台词库
- **自定义角色**: 支持 JSON 配置文件导入

### 3.8 LLM 适配器 `llm_client.py` — `MultiLLMClient`

v3.2 重构为 `agent/llm.py` `LLMRouter` 的薄适配层：

```
pc_agent 各模块 (character_manager, chat_window)
        │
        ▼
  MultiLLMClient (适配器)
  - 保持 chat/chat_stream/chat_simple 接口兼容
  - system_prompt → messages 注入
        │
        ▼
  agent/llm.py LLMRouter
  - 多 provider 路由 + 故障转移
  - Function calling 支持
  - 流式 + 非流式 API
```

- **多模型支持**: DeepSeek / 智谱 AI / 硅基流动
- **故障转移**: 主模型不可用时自动切换备选
- **冷却机制**: 429 → 30 秒, 401/403 → 1 小时

---

## 4. AI Agent 层 — ReAct 智能大脑

### 4.1 入口 `agent_cli.py`

```bash
python agent_cli.py "scan my network for threats"   # 单次执行
python agent_cli.py --chat                            # 交互对话模式
python agent_cli.py --list-tools                      # 列出所有工具
```

### 4.2 ReAct 核心 `agent/core.py` — `AgentCore`

**Think → Act → Observe → Repeat** 循环，最多 10 轮迭代。

### 4.3 LLM 路由 `agent/llm.py` — `LLMRouter`

- 多 provider 轮询 + 故障转移
- 支持 OpenAI 兼容 function calling
- 流式输出 with tool call delta 累积

### 4.4 工具注册表 `agent/tools.py` — `ToolRegistry`

**25 个内置安全工具**:

| 工具名 | 功能 | 依赖 |
|---|---|---|
| `scan_network` | 网络连接扫描 | psutil |
| `scan_processes` | 可疑进程检测 | psutil |
| `check_firewall` | 防火墙/Defender 状态 | netsh + PS |
| `read_security_logs` | Windows 事件日志 | win32evtlog |
| `security_summary` | 综合安全摘要 | 监控模块 |
| `get_system_state` | CPU/内存/磁盘 | psutil |
| `get_listening_ports` | 监听端口列表 | psutil |
| `run_command` | 安全沙箱命令执行 | Sandbox |
| `check_command` | 命令预检 | Sandbox |
| `threat_check_ip` | OTX IP 信誉查询 | AlienVault OTX |
| `threat_check_domain` | OTX 域名信誉 | AlienVault OTX |
| `threat_check_hash` | OTX 文件哈希查询 | AlienVault OTX |
| `threat_pulse_search` | OTX 威胁情报搜索 | AlienVault OTX |
| `defender_status` | Defender 实时状态 | PowerShell |
| `defender_quick_scan` | 快速病毒扫描 | PowerShell |
| `defender_full_scan` | 全盘扫描 | PowerShell |
| `defender_threat_list` | 威胁历史 | PowerShell |
| `defender_update` | 更新病毒库 | PowerShell |
| `cve_lookup` | CVE 漏洞查询 | NIST NVD |
| `cve_search` | CVE 关键词搜索 | NIST NVD |
| `web_search` | DuckDuckGo 搜索 | 纯 HTTP |
| `web_fetch` | 网页抓取 | 纯 HTTP |
| `install_skill` | 安装新技能 | 本地文件 |
| `recommend_mcp_server` | MCP 推荐 | 生成配置 |
| `list_skills` | 列出已安装技能 | 本地文件 |

### 4.5 聊天窗口 ReAct 集成 `chat_window.py`

v3.2 重大升级：AI 对话窗口从纯文本聊天升级为 ReAct 循环。

```
用户: "检查系统安全"
  ↓
LLMWorker ReAct Loop:
  Think:  LLM 分析 → 决定调用 scan_network + check_firewall
  Act:    执行工具 → UI 显示调用状态
  Observe: 工具结果回传 LLM
  Respond: LLM 基于实时数据回复用户
  ↓
UI 显示:
  🔒 调用工具: scan_network
  ✅ scan_network: {"status": "normal", "suspicious_ips": 0}
  🔒 调用工具: check_firewall
  ✅ check_firewall: {"firewall_on": true, "defender_on": true}
  
  安小盾: 系统安全状态良好！防火墙和 Defender 都在运行，
  没有发现可疑连接 (｡･ω･｡)
```

最多 5 轮工具调用迭代，60 秒超时，信号驱动的 UI 更新。

---

## 5. ESP32 固件层 — 硬件终端

### 5.1 固件 `firmware/firmware.ino` (v3.0)

**v3.0 变更**:
- 移除二次元 Chibi 角色位图（v2.0 遗留），改用大号 Kaomoji 颜文字
- 双屏固定切换: 表情屏 + 仪表盘 (按键或 PC 指令)
- 精简动画系统（眨眼 + 呼吸）
- 离线状态 "DISCONNECTED" 明确标识

**双屏设计**:

| 屏幕 0: 表情屏 | 屏幕 1: 仪表盘 |
|---|---|
| 大号颜文字 (･ω･ / ^o^ / >_<) | 安全等级 + 威胁计数 |
| 状态文字 (SECURE / WARNING / DANGER) | 防火墙/Defender 状态 |
| 信号条 + 安全指示灯 | 活跃连接数 + 可疑 IP |
| 眨眼 + 呼吸动画 | CPU/内存 |

**硬件引脚**:

| 组件 | 引脚 |
|---|---|
| OLED SDA/SCL | D21/D22 |
| 蜂鸣器 | D5 |
| RGB LED | D4 |
| 按键 | D0 (BOOT) |

### 5.2 T-Display 固件 `firmware_tdisplay/firmware_tdisplay.ino` (v3.1)

- TTGO T-Display 彩色 TFT (135×240)
- Kaomoji 位图渲染 (`characters/kaomoji_bitmaps.h`)
- 彩色安全等级指示（绿/黄/红）
- CPU/内存进度条

---

## 6. 用户界面层

### 6.1 CLI 命令行 `python main.py`

- 彩色日志输出 (colorlog)
- Ctrl+C 优雅退出
- 适合服务器/后台运行

### 6.2 PyQt5 桌面 GUI `desktop_gui.py`

**极简暗色主题** (`#0d0f12` 主背景):

```
┌─────────────────────────────────────────────────┐
│  AI 网络安全管家                        ● 已连接 │
│  REAL-TIME SECURITY MONITOR                     │
│ ─────────────────────────────────────────────── │
│  [设备屏幕切换]                    [AI 对话]     │
│                                                 │
│  安全概览                                       │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐  │
│  │ ○ SAFE │ │ !  0   │ │ ~ 正常 │ │ ◆ 空闲 │  │
│  │ 安全等级│ │ 活跃威胁│ │ 网络状态│ │ AI 状态│  │
│  └────────┘ └────────┘ └────────┘ └────────┘  │
│                                                 │
│  系统与资源                                     │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐  │
│  │ ● 开启 │ │ ● 开启 │ │ CPU 30%│ │ MEM 45%│  │
│  │ 防火墙  │ │ 防病毒  │ │ ████   │ │ █████  │  │
│  └────────┘ └────────┘ └────────┘ └────────┘  │
└─────────────────────────────────────────────────┘
```

**特性**:
- StatusCard — 极简指标卡片 (图标 + 大数值 + 小标签)
- GaugeCard — 带进度条的资源卡片 (颜色自动: 绿→黄→红)
- 危险脉冲动画 — danger 级别时卡片闪烁
- 系统托盘 — 最小化到托盘，状态色图标 (绿/黄/红)
- 关闭窗口 → 隐藏到托盘 (非退出)
- 设备屏幕切换 — 远程切换 ESP32 的表情屏/仪表盘

### 6.3 AI 对话窗口 `chat_window.py`

**v3.2 ReAct + Tools 版本**:

- **ReAct 循环**: Think → Act → Observe → Respond，最多 5 轮工具调用
- **工具可视化**: 每个工具调用和结果实时显示在聊天界面
- **流式输出**: LLM 回复逐字显示
- **知识库检索**: 对话前搜索历史相关对话作为上下文
- **对话保存**: 清空对话时自动保存到知识库
- **5 个快速操作**: 快速扫描 / 病毒检测 / 漏洞检查 / 安全报告 / 修复建议
- **30 秒看门狗**: 防止 LLM 调用卡死

### 6.4 系统托盘 `system_tray.py`

- pystray + Pillow 托盘图标
- 状态色变化 (绿/黄/红)
- 右键菜单: 立即扫描 / 退出
- 仅在 CLI 模式下启用（GUI 模式内置托盘）

---

## 7. 知识库系统 — 向量化对话记忆

### 7.1 架构 `agent/knowledge_base.py`

```
knowledge_base/
├── conversations/        # Markdown 对话文件
└── chroma/              # ChromaDB 向量数据库
```

### 7.2 三级 Embedding 降级

| 优先级 | 引擎 | 依赖 | 说明 |
|---|---|---|---|
| L1 | `paraphrase-multilingual-MiniLM-L12-v2` | torch | 中英双语 SOTA |
| L2 | ONNX `all-MiniLM-L6-v2` | onnxruntime | 无需 CUDA DLL |
| L3 | TF-IDF 纯 Python | 零依赖 | 关键词匹配兜底 |

当 torch/sentence-transformers 不可用时自动降级。

---

## 8. Skills 技能系统

### 8.1 设计理念

类似 Claude Code 的 Skills 机制。`.md` 文件放入 `skills/` 目录 → Agent 自动发现并注入系统提示词。

### 8.2 文件格式

```markdown
---
name: network-audit
description: Deep network security audit
triggers:
  - "scan network"
---
# 技能内容 (注入到系统提示词)
...
```

### 8.3 当前技能库

| 技能文件 | 描述 |
|---|---|
| `skills/full_audit.md` | 全面安全审计 |
| `skills/network_scan.md` | 网络扫描分析 |
| `skills/process_check.md` | 进程行为检查 |
| `skills/ransomware_check.md` | 勒索软件检测 |

---

## 9. MCP 协议支持

### 9.1 双重角色

**MCP Client** (`agent/mcp_client.py`):
```yaml
# config.yaml
mcp_servers:
  - name: external-tool
    transport: stdio
    command: "python -m some_mcp_server"
  - name: remote-service
    transport: http
    url: "http://localhost:9000/mcp"
```

**MCP Server** (`agent/mcp_server_mode.py`):
```bash
python -m agent.mcp_server_mode
# Claude Code 等外部客户端可直接连接 Guardian 的安全工具
```

### 9.2 协议流程

```
Client                          Server
  │──── initialize ───────────────►│
  │◄─── capabilities ──────────────│
  │──── tools/list ───────────────►│
  │◄─── tool schemas ──────────────│
  │──── tools/call {"name":"x"} ──►│
  │◄─── result ────────────────────│
```

---

## 10. 安全沙箱设计

### 10.1 6 层防护

```
┌─────────────────────────────────────────┐
│ Layer 6: 审计日志                        │
│   每次执行 → sandbox_audit.log          │
├─────────────────────────────────────────┤
│ Layer 5: 文件系统守卫                    │
│   禁止写入非授权目录                     │
├─────────────────────────────────────────┤
│ Layer 4: 资源限制                        │
│   30s / 64MB / 16KB 上限                │
├─────────────────────────────────────────┤
│ Layer 3: Restricted Token               │
│   剥离管理员权限 + 危险特权              │
├─────────────────────────────────────────┤
│ Layer 2: Windows Job Object              │
│   内核级 CPU/内存限制, 自动 kill         │
├─────────────────────────────────────────┤
│ Layer 1: 命令白名单                      │
│   19 个安全命令 + 固定参数               │
└─────────────────────────────────────────┘
```

**原则**: fail-closed — 任何一层失败 → 默认拒绝执行

---

## 11. 遇到的关键问题与解决方案

### 11.1 GBK 编码崩溃 (2026-07-28)

**现象**: `subprocess.py` 持续抛出 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`

**修复**: 所有 `subprocess.run()` 显式指定 `encoding="utf-8", errors="replace"`。

### 11.2 ESP32 频繁断连 (2026-07-28)

**现象**: 连接成功数秒后 "Write timeout" → 重连风暴

**根因**: 线程泄漏（每次重连创建新线程）、串口泄漏（不关闭旧连接）、并发重连

**修复**: `_handle_disconnect()` 先停旧线程，关闭旧串口，`_reconnect_lock` 防重入。

### 11.3 智谱 GLM 不支持 System Role

**解决方案**: 适配器自动检测 Provider，对智谱将 system prompt 合并到首条 user 消息。

### 11.4 torchaudio DLL 错误 (2026-07-29)

**现象**: `无法定位程序输入点 torch_library_impl 于 torchaudio.pyd`

**原因**: 虚拟环境中 torchaudio 二进制损坏（版本号匹配但文件不完整）

**修复**: `pip install --force-reinstall torchaudio` 重装

### 11.5 聊天窗口发送消息无响应 (2026-07-29)

**根因**:
1. "思考中..." 占位符被错误地加入对话历史发送给 LLM
2. tool_calls 格式与 DeepSeek API 不完全兼容（缺少 `"type": "function"` 字段）

**修复**:
1. 对话历史构建与 UI 占位符分离
2. tool_calls 格式规范化（添加 `type` 字段，移除内部字段 `arguments_parsed`）

---

## 12. 技术栈总览

| 层 | 技术 | 说明 |
|---|---|---|
| **嵌入式** | Arduino C++ / ESP32 | 固件开发 |
| **显示驱动** | Adafruit SSD1306 + GFX / TFT_eSPI | OLED / TFT |
| **通信协议** | JSON over Serial (115200bps) | PC ↔ ESP32 |
| **PC Agent** | Python 3.10+ | 主控程序 |
| **系统监控** | psutil, pywin32 (win32evtlog) | 进程/网络/事件日志 |
| **LLM 路由** | agent/llm.py → LLMRouter | 多 provider 故障转移 |
| **LLM 适配器** | pc_agent/llm_client.py → MultiLLMClient | 封装 LLMRouter |
| **桌面 GUI** | PyQt5 + QSS | 暗色极简主题 |
| **ReAct 对话** | chat_window.py → LLMWorker | Think→Act→Observe 循环 |
| **系统托盘** | pystray + Pillow | CLI 模式后台 |
| **向量数据库** | ChromaDB | 对话语义检索 |
| **Embedding** | sentence-transformers / ONNX / TF-IDF | 三级降级 |
| **MCP 协议** | JSON-RPC 2.0 | Client + Server |
| **威胁情报** | AlienVault OTX + NIST NVD | 免费 API |
| **搜索** | DuckDuckGo Lite | 免费无 Key |
| **安全沙箱** | Job Object + Restricted Token | 6 层隔离 |
| **测试** | pytest + unittest.mock | 单元测试 |

---

## 13. 项目文件清单

```
ai-security-guardian/
│
├── README.md                          # 项目介绍 + 快速开始
├── PROJECT_FULL_STORY.md              # 本文档
├── agent_cli.py                       # CLI Agent 入口
├── requirements-lock.txt              # 锁定依赖版本
├── pytest.ini                         # pytest 配置
├── .gitignore
│
├── pc_agent/                          # 💻 PC 端安全引擎
│   ├── main.py                        #   主入口 GuardianController
│   ├── config.yaml                    #   全局配置 (LLM/MCP/设备)
│   ├── requirements.txt               #   Python 依赖
│   ├── device_bridge.py               #   设备通信 (Serial/WiFi)
│   ├── security_monitor.py            #   安全事件监控 (EventLog)
│   ├── network_monitor.py             #   网络威胁检测
│   ├── process_monitor.py             #   可疑进程检测
│   ├── firewall_checker.py            #   防火墙/Defender 检查
│   ├── character_manager.py           #   角色表情+台词管理
│   ├── llm_client.py                  #   LLM 适配器 (封装 agent/llm.py)
│   ├── desktop_gui.py                 #   PyQt5 桌面 GUI
│   ├── chat_window.py                 #   AI 对话窗口 (ReAct + Tools)
│   ├── system_tray.py                 #   系统托盘
│   ├── ai_status.py                   #   AI 状态追踪
│   └── __init__.py
│
├── agent/                             # 🧠 AI Agent 子系统
│   ├── __init__.py
│   ├── core.py                        #   ReAct Agent 核心循环
│   ├── config.py                      #   Agent 配置 + LLMProvider
│   ├── llm.py                         #   LLM 路由器 (function calling)
│   ├── tools.py                       #   工具注册表 + 25 个内置工具
│   ├── mcp_client.py                  #   MCP JSON-RPC 客户端
│   ├── mcp_server_mode.py             #   MCP Server 模式
│   ├── sandbox.py                     #   6 层安全沙箱
│   ├── skill_loader.py                #   .md 技能自动加载
│   ├── knowledge_base.py              #   向量知识库 (ChromaDB)
│   ├── defender_tools.py              #   Defender + NVD CVE
│   ├── otx_tools.py                   #   AlienVault OTX 威胁情报
│   ├── web_tools.py                   #   DuckDuckGo 搜索 + 抓取
│   └── installer.py                   #   技能安装 + MCP 推荐
│
├── firmware/                          # 🔌 ESP32 固件
│   ├── firmware.ino                   #   主固件 OLED 128×64 (v3.0)
│   ├── firmware_tdisplay/
│   │   └── firmware_tdisplay.ino      #   T-Display TFT 135×240 (v3.1)
│   └── characters/
│       └── kaomoji_bitmaps.h          #   颜文字 PROGMEM 位图
│
├── tests/                             # 🧪 单元测试
│   ├── conftest.py                    #   共享 fixtures + mock
│   ├── test_controller.py             #   GuardianController 测试
│   ├── test_firewall_checker.py       #   FirewallChecker 测试
│   ├── test_network_monitor.py        #   NetworkMonitor 测试
│   ├── test_character_manager.py      #   CharacterManager 测试
│   └── test_device_bridge.py          #   DeviceBridge 测试
│
├── skills/                            # 📦 Agent 技能文件
│   ├── full_audit.md                  #   全面安全审计
│   ├── network_scan.md                #   网络扫描分析
│   ├── process_check.md               #   进程行为检查
│   ├── ransomware_check.md            #   勒索软件检测
│   └── user/                          #   用户自定义技能
│
├── result/                            # 📐 设计资料与工具
│   ├── diagrams/                      #   12 张系统架构图 (.drawio)
│   ├── dify_designs/                  #   Dify 提示词设计
│   ├── docs/                          #   硬件文档
│   ├── enclosure/                     #   3D 外壳设计
│   ├── installer/                     #   一键安装脚本
│   └── tools/                         #   辅助工具
│
├── knowledge_base/                    # 🧠 本地知识库
│   ├── conversations/                 #   Markdown 对话文件
│   └── chroma/                        #   ChromaDB 向量数据
│
└── .venv/                             # 🐍 Python 虚拟环境
```

---

## 致谢

- ESP32 & Arduino 社区
- Adafruit SSD1306 驱动库
- psutil 系统监控库
- ChromaDB 向量数据库
- AlienVault OTX 免费威胁情报
- NIST NVD 免费漏洞数据库
- DeepSeek、智谱 AI、硅基流动
- PyQt5 桌面框架

---

**🛡️ 保护你的数字世界，从一个微小的设备开始。**
