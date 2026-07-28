# 🛡️ AI 网络安全管家 — 项目全纪实

> **作者**: Chen Ziye (陈梓烨)
> **日期**: 2026-07-28
> **版本**: v3.0 · MINIMAL
> **定位**: 嵌入式 + 桌面端 + AI Agent 三位一体的开源网络安全守护系统

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [PC Agent 层 — 安全监控引擎](#3-pc-agent-层--安全监控引擎)
4. [AI Agent 层 — ReAct 智能大脑](#4-ai-agent-层--react-智能大脑)
5. [ESP32 固件层 — 硬件终端](#5-esp32-固件层--硬件终端)
6. [用户界面层 — 4 种交互方式](#6-用户界面层--4-种交互方式)
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
- 🤖 **AI 驱动分析** — 多模型 LLM 客户端（DeepSeek / 智谱 / 硅基流动），支持故障转移
- 📟 **物理终端** — ESP32 + OLED 屏幕，显示二次元角色"安小盾"的表情和台词
- 💬 **2 种交互界面** — CLI 命令行、PyQt5 桌面 GUI
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
    │ Character    │ JSON │  └────┬─────┘  └────┬─────┘  └──────┬────────┘  │
    │ Engine       │Serial│       └─────────┬──┴───────────────┘            │
    │ (安小盾)      │      │                 ▼                               │
    │ Buzzer+LED   │      │  ┌──────────────────────────────────────────┐   │
    └──────────────┘      │  │        GuardianController                 │   │
                          │  │  (状态管理 + 安全等级计算 + 扫描循环)       │   │
                          │  └────────────┬─────────────────────────────┘   │
                          │               │                                  │
                          │  ┌────────────┼────────────┐                    │
                          │  ▼            ▼            ▼                    │
                          │ Device    Character    LLM Client               │
                          │ Bridge    Manager    (MultiLLMClient)           │
                          │ (Serial/  (表情+台词   (DeepSeek/智谱/           │
                          │  WiFi)    +LLM对话)    硅基流动)                 │
                          │                                     │           │
                          │  ┌──────────────┬──────────────────┤           │
                          │  ▼              ▼                  ▼           │
                          │ Web Dashboard  Desktop GUI      System Tray    │
                          │ (Flask :5000)  (PyQt5)          (pystray)      │
                          │                                                   │
                          │  ┌──────────────────────────────────────────┐   │
                          │  │            AI Agent 层                     │   │
                          │  │  ┌────────┐  ┌────────┐  ┌────────────┐  │   │
                          │  │  │ReAct   │  │MCP     │  │Skill       │  │   │
                          │  │  │Core    │  │Client  │  │Manager     │  │   │
                          │  │  └───┬────┘  └───┬────┘  └─────┬──────┘  │   │
                          │  │      │           │             │          │   │
                          │  │  ┌───┴───────────┴─────────────┴──────┐   │   │
                          │  │  │         Tool Registry              │   │   │
                          │  │  │  (built-in + MCP-discovered)       │   │   │
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
                          │  │  (TF-IDF fallback when no GPU)           │   │
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
        ├──► DeviceBridge ──► ESP32 OLED (安全仪表盘 + 角色表情)
        ├──► Web Dashboard ──► 浏览器实时面板
        ├──► Desktop GUI ──► PyQt5 桌面窗口
        ├──► System Tray ──► 任务栏图标 + 右键菜单
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
            'ai_status': 'idle',    # AI 工作状态
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

    def _scan_loop(self):
        """主扫描循环 (默认5秒间隔):
        1. 网络扫描 → 检查可疑 IP/端口/C2 通信
        2. 进程扫描 → 检测恶意进程/异常资源
        3. 防火墙检查 → 验证 FW/Defender 状态
        4. 系统资源 → psutil CPU/内存
        5. 计算安全等级 → safe/warning/danger
        6. 推送状态到 ESP32
        7. 推送角色表情+台词
        8. 有威胁时 LLM 安全分析
        """
```

**启动参数**:

| 参数 | 说明 |
|---|---|
| `python main.py` | CLI 模式 (默认) |
| `python main.py --gui` | PyQt5 桌面 GUI 模式 |
| `python main.py --no-device` | 不连接 ESP32 (纯 Web) |
| `python main.py --no-tray` | 禁用系统托盘 |
| `python main.py --no-dashboard` | 禁用 Web Dashboard |
| `python main.py --config my.yaml` | 使用自定义配置 |

### 3.2 网络监控 `network_monitor.py` — `NetworkMonitor`

- **技术**: `psutil.net_connections(kind='inet')`
- **恶意端口库**: 内置 20+ 常见 C2/后门端口 (4444 Metasploit, 31337 Back Orifice, 6666 IRC C2 等)
- **可疑 IP 段**: 已知攻击 IP 段检测 (5.188.*, 185.220.* Tor 出口节点等)
- **高频连接检测**: 同 IP 短时间内连接 >50 次标为可疑
- **监听端口收集**: `get_listening_ports()` → 供漏洞检查模块使用

### 3.3 进程监控 `process_monitor.py` — `ProcessMonitor`

- **技术**: `psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'exe', 'cmdline'])`
- **白名单**: 30+ Windows 系统进程 (svchost, lsass, dwm 等)
- **黑名单**: 20+ 黑客工具特征 (mimikatz, nmap, metasploit, cobalt strike, wireshark, hashcat 等)
- **异常检测**: CPU >80% / 内存 >80% 告警
- **进程操作**: `get_process_tree(pid)` / `kill_process(pid)`

### 3.4 防火墙检查 `firewall_checker.py` — `FirewallChecker`

- **多级降级策略**:
  1. `netsh advfirewall show allprofiles state` (最快)
  2. PowerShell `Get-NetFirewallProfile` (备选)
  3. `sc query mpssvc` 服务检查 (兜底)
- **Defender 检测**:
  1. PowerShell `Get-MpComputerStatus` (最可靠)
  2. `psutil` 检查 MsMpEng.exe 进程
  3. `sc query WinDefend` 服务检查
- **编码修复**: 所有 `subprocess.run()` 显式指定 `encoding="utf-8", errors="replace"` 避免 GBK 解码错误
- **缓存机制**: 30秒检查间隔，连续失败用缓存兜底

### 3.5 安全事件监控 `security_monitor.py` — `SecurityMonitor`

- **Windows 安全日志**: 通过 `win32evtlog` 读取 Security 日志，关注 18 种可疑 EventID
  - 4625 登录失败、4648 显式凭据登录、4688 进程创建、4720 用户创建等
- **Defender 日志**: 读取 Microsoft-Windows-Windows Defender/Operational
- **摘要统计**: 失败登录数、新进程数、新用户数、风险等级

### 3.6 设备通信桥 `device_bridge.py` — `DeviceBridge`

- **双模通信**: Serial (USB) + WiFi (TCP Socket)
- **自动检测**: 扫描 COM 口识别 CP210x/CH340/CH9102 等 ESP32 常见芯片
- **心跳保活**: 每 2 秒 ping/pong 维持连接
- **串口消费**: 独立线程持续读取，防止缓冲区积压
- **断连恢复**: 防重入锁保护，旧端口关闭 + 旧线程停止后再重连 (v2 修复)
- **通信协议**: JSON over Serial

```json
{"cmd": "update", "sec_level": "safe", "threat_count": 0, ...}
{"cmd": "alert", "message": "检测到可疑连接: 192.168.1.100:4444"}
{"cmd": "expression", "expression": 4}
{"cmd": "say", "text": "主人! 防火墙怎么关了!"}
{"cmd": "screen", "screen": 1}
```

### 3.7 角色管理器 `character_manager.py` — `CharacterManager`

- **表情系统**: 8 种表情 (idle/happy/working/worried/angry/sleep/love/greeting)
- **本地台词库**: 12 个类别 60+ 句预设台词，避免重复 (used_lines 集合)
- **LLM 动态生成**: 调用 `MultiLLMClient.generate_companion_line()` 实时生成台词
- **LLM 降级策略**: 连续失败 5 次 → 冷却 30 秒，自动切回本地台词库
- **触发机制**:
  - `startup` → 开机欢迎 (无冷却)
  - `threat` → 立即告警
  - `cleared` → 威胁清除庆祝
  - `auto` → 安全等级变化时主动说话 (15 秒冷却)
  - `interaction` → 用户互动
- **自定义角色**: 支持 JSON 配置文件导入 (`load_character(path)`)
- **安全分析**: 威胁检测时调用 LLM 分析并给出建议

### 3.8 LLM 客户端 `llm_client.py` — `MultiLLMClient`

- **多模型支持**: DeepSeek / 智谱 AI / 硅基流动 / 任何 OpenAI 兼容 API
- **故障转移**: 主模型不可用时自动切换备选
- **冷却机制**: 429 → 30 秒, 401/403 → 1 小时, 超时 → 60 秒
- **智谱适配**: 自动将 system role 合并到首条 user 消息 (GLM 不支持 system)
- **流式输出**: `chat_stream()` 生成器，逐 token 返回
- **用量统计**: `UsageStats` 追踪调用次数、token 消耗、费用估算
- **安全专用方法**:
  - `analyze_security_event(state)` → 30 字安全建议
  - `explain_threat(desc)` → 通俗威胁解释
  - `generate_companion_line(state)` → 15 字角色台词

**预设模型**:

| 预设名 | 提供商 | 模型 | 费用 |
|---|---|---|---|
| `deepseek-chat` | DeepSeek | deepseek-chat | ~2元/百万token |
| `deepseek-reasoner` | DeepSeek | deepseek-reasoner | ~4元/百万token |
| `glm-4-flash` | 智谱 | glm-4-flash | **免费** |
| `glm-4` | 智谱 | glm-4 | ~50元/百万token |

---

## 4. AI Agent 层 — ReAct 智能大脑

### 4.1 入口 `agent_cli.py`

独立于 PC Agent 的 AI 对话入口：

```bash
python agent_cli.py "scan my network for threats"   # 单次执行
python agent_cli.py --chat                            # 交互对话模式
python agent_cli.py --skill full-audit                # 启动指定技能
python agent_cli.py --list-tools                      # 列出所有工具
```

### 4.2 ReAct 核心 `agent/core.py` — `AgentCore`

**Think → Act → Observe → Repeat** 循环：

```python
class AgentCore:
    """
    LLM Router (DeepSeek-v4-pro default)
        │
    Tool Registry (built-in + MCP-discovered + skills)
        │
    +-- Built-in tools  (scan_network, check_firewall, ...)
    +-- MCP Client       (external MCP servers, JSON-RPC 2.0)
    +-- Skill Manager    (local .md files, prompt injection)
    +-- Knowledge Base   (vector search for past conversations)
    """
```

最多 10 轮迭代，每轮：
1. LLM 返回工具调用 or 文本回复
2. 如果是工具调用 → 执行 → 结果注入对话 → 继续
3. 如果是文本回复 → 返回给用户

### 4.3 LLM 路由 `agent/llm.py` — `LLMRouter`

- 多 provider 轮询 + 故障转移
- 支持 OpenAI 兼容 function calling
- 相同冷却/降级逻辑

### 4.4 工具注册表 `agent/tools.py` — `ToolRegistry`

**内置安全工具 (10+)**:

| 工具名 | 功能 | 依赖 |
|---|---|---|
| `security_summary` | 综合安全摘要 | psutil + 监控模块 |
| `scan_network` | 网络连接扫描 | NetworkMonitor |
| `scan_processes` | 可疑进程检测 | ProcessMonitor |
| `check_firewall` | 防火墙/Defender 状态 | FirewallChecker |
| `read_security_logs` | Windows 事件日志 | SecurityMonitor |
| `get_system_state` | CPU/内存/运行时间 | psutil |
| `get_listening_ports` | 监听端口列表 | NetworkMonitor |
| `run_command` | 安全沙箱命令执行 | Sandbox |
| `web_search` | DuckDuckGo 搜索 | 纯 HTTP (免费) |
| `web_fetch` | 网页抓取 | 纯 HTTP |
| `threat_check_ip` | OTX IP 信誉查询 | AlienVault OTX (免费) |
| `threat_check_domain` | OTX 域名信誉 | AlienVault OTX |
| `threat_check_hash` | OTX 文件哈希查询 | AlienVault OTX |
| `defender_status` | Defender 实时状态 | PowerShell |
| `defender_quick_scan` | 快速病毒扫描 | PowerShell |
| `defender_full_scan` | 全盘扫描 | PowerShell |
| `defender_threat_list` | 威胁历史 | PowerShell |
| `nvd_cve_lookup` | CVE 漏洞查询 | NIST NVD API (免费) |
| `nvd_cve_search` | CVE 关键词搜索 | NIST NVD API |
| `install_skill` | 安装新技能 | 本地文件写入 |
| `recommend_mcp_server` | MCP 推荐 | 生成配置片段 |

### 4.5 MCP 客户端 `agent/mcp_client.py` — `MCPManager`

- JSON-RPC 2.0 协议，符合 MCP 2024-11-05 规范
- 双传输模式: **stdio** (子进程) + **HTTP** (远程服务)
- `initialize` → `tools/list` → `tools/call` 标准流程
- 发现的工具自动注册到 ToolRegistry

### 4.6 MCP 服务端 `agent/mcp_server_mode.py` — `GuardianMCPServer`

反过来将 Guardian 的工具暴露为 MCP Server：
```bash
python -m agent.mcp_server_mode   # stdio 模式
```
外部 MCP Client (包括 Claude Code!) 可直接连接使用 Guardian 的安全工具。

### 4.7 安全沙箱 `agent/sandbox.py`

多层进程隔离：
1. **命令白名单** — 19 个安全命令 + 限定参数 (ipconfig, netstat, tasklist 等)
2. **Windows Job Object** — 内核级 CPU/内存限制
3. **Restricted Token** — 剥离管理员权限和危险特权
4. **资源限制** — 30s 超时, 64MB 内存, 16KB 输出
5. **文件系统守卫** — 禁止写入非授权目录
6. **审计日志** — 每次执行记录到 `sandbox_audit.log`

### 4.8 外部威胁情报 `agent/otx_tools.py`

- **AlienVault OTX** — 免费威胁情报 API
- IP/Domain/Hash 信誉查询 + Pulse 搜索
- 5 分钟本地缓存减少 API 调用

### 4.9 Defender + NVD 工具 `agent/defender_tools.py`

- Windows Defender 扫描、更新、威胁历史 (PowerShell)
- NIST NVD CVE 查询/搜索 (免费 US 政府 API)

### 4.10 Web 工具 `agent/web_tools.py`

- **web_search**: DuckDuckGo Lite (无 API Key、无追踪)
- **web_fetch**: URL → 纯文本 (HTML 标签剥离, 64KB 限制, 8KB 输出)

---

## 5. ESP32 固件层 — 硬件终端

### 5.1 固件 `firmware/firmware.ino` (v3.0 精简版)

**变更**:
- 移除二次元 Chibi 角色位图，改用大号 Kaomoji 颜文字
- 双屏固定切换: 表情屏 + 仪表盘 (按键或 PC 指令)
- 不再自动轮播，用户手动控制
- 离线状态 "DISCONNECTED" 明确标识

**双屏设计**:

| 屏幕 0: 表情屏 | 屏幕 1: 仪表盘 |
|---|---|
| 大号颜文字 (･ω･ / ^o^ / >_<) | 安全等级 + 威胁计数 |
| 角色状态文字 | 防火墙/Defender 状态 |
| 信号条 + 安全指示灯 | 活跃连接数 + 可疑 IP |
| 动画: 眨眼 + 呼吸 | CPU/内存资源 |

**硬件引脚**:

| 组件 | 引脚 |
|---|---|
| OLED SDA | D21 |
| OLED SCL | D22 |
| 蜂鸣器 | D5 |
| RGB LED | D4 |
| 按键 | D0 (BOOT) |



---

## 6. 用户界面层 — 4 种交互方式

### 6.1 CLI 命令行 `python main.py`

- 彩色日志输出 (colorlog)
- Ctrl+C 优雅退出
- 适合服务器/后台运行

### 6.2 PyQt5 桌面 GUI `desktop_gui.py` — `DesktopGUI`

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
│                                                 │
│  威胁与事件                                     │
│  ┌─────────────────────────────────────────┐   │
│  │   系统运行正常，无活跃威胁                 │   │
│  └─────────────────────────────────────────┘   │
│ ─────────────────────────────────────────────── │
│  刷新 15:58:08 · 连接 25 · 可疑IP 0 · 运行 3h │
└─────────────────────────────────────────────────┘
```

**特性**:
- StatusCard — 极简指标卡片 (图标 + 大数值 + 小标签)
- GaugeCard — 带进度条的资源卡片 (颜色自动: 绿→黄→红)
- 危险脉冲动画 — danger 级别时卡片闪烁
- 系统托盘 — 最小化到托盘，状态色图标 (绿/黄/红)
- 关闭窗口 → 隐藏到托盘 (非退出)
- 设备屏幕切换 — 远程切换 ESP32 的表情屏/仪表盘

### 6.3 AI 对话窗口 `chat_window.py` — `ChatWindow`

与桌面 GUI 统一设计语言的极简对话窗口：

**功能**:
- **流式输出**: LLM 回复逐字显示
- **知识库检索**: 对话前搜索历史相关对话作为上下文
- **对话保存**: 清空对话时自动保存到知识库
- **5 个快速操作**: 快速扫描 / 病毒检测 / 漏洞检查 / 安全报告 / 修复建议
- **30 秒看门狗**: 防止 LLM 调用卡死
- Ctrl+Enter 发送消息
- 用户气泡 (深蓝灰) / AI 气泡 (卡片色) / 系统气泡 (微绿调)

### 6.4 Web Dashboard `web_dashboard.py` — Flask `:5000`

- Flask 开发服务器，`http://127.0.0.1:5000`
- 实时安全状态面板
- 深色 UI 主题
- REST API 接口供外部调用

### 6.5 系统托盘 `system_tray.py` — `SystemTrayApp`

- pystray + Pillow 托盘图标
- 状态色变化 (绿/黄/红)
- 右键菜单: 状态信息 / 退出

---

## 7. 知识库系统 — 向量化对话记忆

### 7.1 架构 `agent/knowledge_base.py`

```
knowledge_base/
├── conversations/        # Markdown 对话文件
│   ├── 2026-07-28_103322.md
│   └── 2026-07-28_113402.md
└── chroma/              # ChromaDB 向量数据库
```

### 7.2 双模 Embedding

| 模式 | 引擎 | 大小 | 质量 |
|---|---|---|---|
| **生产模式** | `paraphrase-multilingual-MiniLM-L12-v2` | ~470MB | 中英双语 SOTA |
| **后备模式** | `_FallbackEmbedding` (TF-IDF) | 0 | 纯 Python 零依赖 |

当 `sentence-transformers` 未安装时自动切换到 TF-IDF 后备方案。

### 7.3 API

```python
kb = get_knowledge_base()

# 保存对话
conv_id = kb.add_conversation(messages, metadata)

# 语义检索
context = kb.build_context(user_query, top_k=3)

# 统计
kb.count              # 总记录数
kb.conversation_count # 对话数
```

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
  - "check network"
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

### 8.4 Skill 生命周期

1. Agent 启动 → `SkillManager.load_all()` 扫描目录
2. 用户输入 → `SkillManager.match_triggers()` 匹配触发词
3. 匹配成功 → Skill 内容注入系统提示词
4. 该轮对话结束 → Skill 退出上下文

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
# Claude Code 等外部客户端可直接连接
```

### 9.2 协议流程

```
Client                          Server
  │                                │
  │──── initialize ───────────────►│
  │◄─── capabilities ──────────────│
  │──── initialized ──────────────►│
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
│   禁止写入 非授权目录                    │
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

### 10.2 白名单命令

`ipconfig`, `netstat`, `tasklist`, `whoami`, `systeminfo`, `hostname`, `ver`, `ping`, `tracert`, `nslookup`, `route`, `arp`, `getmac`, `driverquery`, `sc query*`, `schtasks /query*`, `powercfg`, `wmic`, `dir`, `set`, `findstr`

### 10.3 原则

**fail-closed**: 任何一层失败 → 默认拒绝执行

---

## 11. 遇到的关键问题与解决方案

### 11.1 GBK 编码崩溃 (2026-07-28)

**现象**: `subprocess.py` 的 `_readerthread` 持续抛出 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`

**根因**: Windows 中文系统默认编码 GBK (cp936)。`subprocess.run(capture_output=True)` 不加 `encoding` 参数时用系统编码解码管道输出。当 `netsh`/`sc` 命令输出包含 GBK 无法解码的字节时，内部 reader 线程崩溃。

**修复**: 所有 `subprocess.run()` 显式指定 `encoding="utf-8", errors="replace"`。涉及文件:
- `pc_agent/firewall_checker.py` — 5 处
- `agent/tools.py` — 1 处
- `agent/defender_tools.py` — 已有 (无需修改)

### 11.2 ESP32 频繁断连 (2026-07-28)

**现象**: 连接成功数秒后 "Write timeout" → 重连风暴, `_readerthread` 报错数量不断增长

**根因**:
1. **线程泄漏**: 每次重连 `_start_background_tasks()` 创建新心跳/reader 线程，旧的不死
2. **串口泄漏**: 重连时不关闭旧 `serial.Serial` 对象，端口资源泄露
3. **并发重连**: 心跳线程和扫描线程同时触发 `_handle_disconnect()`，多个重连流程并行

**修复** (`device_bridge.py`):
1. `_handle_disconnect()` 先设 `_running=False` 停旧线程
2. 重连前 `close()` 旧串口 + 设为 `None`
3. 加 `_reconnect_lock` 防重入，`try/finally` 保证释放

### 11.3 智谱 GLM 不支持 System Role

**现象**: 智谱 API 不接受 `role: system` 的消息

**解决方案**: `MultiLLMClient._build_messages()` 自动检测 Provider，对智谱将 system prompt 合并到首条 user 消息前缀。

### 11.4 管理员权限缺失

**现象**: 约 30% 功能不可用（安全日志、Defender 详情、进程终止、防火墙规则修改）

**解决方案**: 启动时检查权限，明确列出受影响的功能，提示用户以管理员身份运行。

---

## 12. 技术栈总览

| 层 | 技术 | 说明 |
|---|---|---|
| **嵌入式** | Arduino C++ / ESP32 | 固件开发 |
| **显示驱动** | Adafruit SSD1306 + GFX | OLED 128×64 |
| **通信协议** | JSON over Serial (115200bps) | PC ↔ ESP32 |
| **PC Agent** | Python 3.10+ | 主控程序 |
| **系统监控** | psutil, pywin32 (win32evtlog) | 进程/网络/事件日志 |
| **防火墙检查** | subprocess (netsh + PowerShell) | 多级降级 |
| **LLM** | OpenAI-compatible API | DeepSeek/智谱/硅基流动 |
| **Web Dashboard** | Flask | 实时面板 |
| **桌面 GUI** | PyQt5 + QSS | 暗色极简主题 |
| **系统托盘** | pystray + Pillow | 后台运行 |
| **向量数据库** | ChromaDB | 对话语义检索 |
| **Embedding** | sentence-transformers (MiniLM) | 后备 TF-IDF |
| **MCP 协议** | JSON-RPC 2.0 | 工具扩展 |
| **威胁情报** | AlienVault OTX + NIST NVD | 免费 API |
| **搜索** | DuckDuckGo Lite | 免费无 Key |
| **测试** | pytest + unittest.mock | 单元测试 |
| **包管理** | pip + requirements.txt | Python 依赖 |

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
├── .gitignore                         # Git 忽略规则
│
├── pc_agent/                          # 💻 PC 端安全引擎
│   ├── main.py                        #   主入口 GuardianController
│   ├── config.yaml                    #   全局配置
│   ├── requirements.txt               #   Python 依赖
│   ├── device_bridge.py               #   设备通信 (Serial/WiFi)
│   ├── security_monitor.py            #   安全事件监控 (EventLog)
│   ├── network_monitor.py             #   网络威胁检测 (psutil)
│   ├── process_monitor.py             #   可疑进程检测
│   ├── firewall_checker.py            #   防火墙/Defender 检查
│   ├── character_manager.py           #   角色表情+台词管理
│   ├── llm_client.py                  #   多模型 LLM 客户端
│   ├── web_dashboard.py               #   Flask Web 仪表盘
│   ├── desktop_gui.py                 #   PyQt5 桌面 GUI
│   ├── chat_window.py                 #   AI 对话窗口
│   ├── system_tray.py                 #   系统托盘
│   ├── ai_status.py                   #   AI 状态追踪
│   └── __init__.py                    #   包初始化
│
├── agent/                             # 🧠 AI Agent 子系统
│   ├── __init__.py
│   ├── core.py                        #   ReAct Agent 核心循环
│   ├── config.py                      #   Agent 配置 + 系统提示词
│   ├── llm.py                         #   LLM 路由器 (function calling)
│   ├── tools.py                       #   工具注册表 + 内置工具
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
│   ├── character_engine.h             #   角色动画引擎
│   ├── characters/
│   │   ├── default_chibi.h            #   OLED 角色精灵 (GFX 过程绘制)
│   │   ├── default_chibi_tft.h        #   TFT 彩色精灵 (RGB565)
│   │   └── kaomoji_bitmaps.h          #   颜文字 PROGMEM 位图
│   └── oled_test/
│       └── oled_test.ino              #   OLED I2C 诊断工具
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
│   └── ransomware_check.md            #   勒索软件检测
│
├── dify_designs/                      # 🎨 Dify 提示词设计
│   ├── README.md
│   └── system_prompt.md
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
├── tools/                             # 🔧 辅助工具
│   ├── image_to_character.py          #   PNG → C header 角色转换器
│   └── build_resume.py                #   简历生成器 (非项目相关)
│
├── .env                               # 🔑 环境变量 (API Keys, 不入库)
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
- DuckDuckGo 免费搜索引擎

---

**🛡️ 保护你的数字世界，从一个微小的设备开始。**
