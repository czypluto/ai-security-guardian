# 📊 AI 网络安全管家 — Draw.io 图表集

本目录包含 12 张与实训报告配套的 draw.io 图表，覆盖架构图、流程图、时序图、ER图、部署图等。

所有 `.drawio` 文件可直接在 [draw.io](https://app.diagrams.net/) 或 VS Code Draw.io 插件中打开和编辑。

---

## 图表清单

| 编号 | 文件名 | 图表类型 | 对应报告章节 |
|------|--------|----------|-------------|
| 01 | `01_系统整体架构图.drawio` | 分层架构图 | §4.1 系统架构设计 (图4-1) |
| 02 | `02_系统主流业务流程图.drawio` | 业务流程图 | §4.3 系统业务流程设计 (图4-2) |
| 03 | `03_系统功能模块图.drawio` | 功能模块图 | §4.2 系统功能设计 |
| 04 | `04_ReAct核心循环流程图.drawio` | 算法流程图 | §5.2.1 ReAct 核心循环 |
| 05 | `05_安全沙箱6层防护架构图.drawio` | 安全架构图 | §5.2.3 安全沙箱 |
| 06 | `06_PC与ESP32通信时序图.drawio` | UML 时序图 | §5.1 PC Agent + §5.3 ESP32 固件 |
| 07 | `07_系统数据流图_DFD.drawio` | 数据流图 (DFD) | §4 系统概要设计 |
| 08 | `08_系统部署图.drawio` | UML 部署图 | §2 相关理论与技术 |
| 09 | `09_MCP协议交互时序图.drawio` | UML 时序图 | §2.4 MCP 协议 + §5.2 AI Agent |
| 10 | `10_防火墙多级降级策略流程图.drawio` | 策略流程图 | §5.1.4 FirewallChecker |
| 11 | `11_知识库RAG流程图.drawio` | RAG 流程图 | §2.4 向量知识库 + §5.2 |
| 12 | `12_知识库ER图.drawio` | 实体关系图 (ER) | §4.4 数据库设计 |

---

## 图表详细说明

### 01. 系统整体架构图
展示系统四层分层架构：硬件层 (ESP32) → PC监控层 → AI Agent层 → 用户界面层，以及各层之间的数据流向。

### 02. 系统主流业务流程图
从系统启动到扫描循环的完整业务流程，包含威胁检测分支 (safe/warning/danger)、LLM分析触发和ESP32告警。

### 03. 系统功能模块图
展示8大功能模块 (安全监控、AI Agent、用户界面、设备通信、角色系统、知识库、ESP32固件、扩展能力) 及其子功能。

### 04. ReAct 核心循环流程图
Think→Act→Observe→Repeat 循环的详细流程，包含技能匹配、知识库检索、工具调用、流式输出和对话保存。

### 05. 安全沙箱6层防护架构图
从外到内6层防护：Layer 6 审计日志 → Layer 5 文件系统守卫 → Layer 4 资源限制 → Layer 3 Restricted Token → Layer 2 Windows Job Object → Layer 1 命令白名单。设计原则: fail-closed。

### 06. PC↔ESP32 通信时序图
GuardianController → DeviceBridge → ESP32 之间的完整通信时序，包含心跳 (ping/pong)、状态推送 (update)、屏幕切换、威胁告警和断连恢复流程。

### 07. 系统数据流图 (DFD Level 1)
展示6个处理过程 (P1-P6)、4个数据存储、5个外部实体之间的数据流向。

### 08. 系统部署图
展示 Windows PC 节点 (Python运行时+各组件)、ESP32 硬件节点、外部云服务节点 (DeepSeek/智谱/OTX/NVD) 以及它们之间的通信协议。

### 09. MCP 协议交互时序图
双角色展示：(A) Guardian 作为 MCP Client 连接外部工具服务器的 initialize→tools/list→tools/call 流程；(B) Guardian 作为 MCP Server 暴露安全工具给 Claude Code 等外部客户端。

### 10. 防火墙多级降级策略流程图
防火墙检查 (netsh→PowerShell→sc query) 和 Defender 检查 (PowerShell→psutil→sc query) 各自的3级降级链路，包含缓存兜底机制和 GBK 编码修复说明。

### 11. 知识库 RAG 流程图
展示写入路径 (对话保存→Embedding→ChromaDB+Markdown) 和读取路径 (问题→向量化→语义检索→注入Prompt)，以及 Embedding 双模降级策略 (MiniLM vs TF-IDF)。

### 12. 知识库 ER 图
展示 4 个核心实体的逻辑数据模型：Conversation (对话)、Message (消息)、VectorDocument (向量文档)、Skill (技能文件)、SandboxAudit (沙箱审计日志)。

---

## 使用方式

1. 打开 [draw.io](https://app.diagrams.net/)
2. 文件 → 打开 → 选择 `.drawio` 文件
3. 可导出为 PNG / SVG / PDF 插入报告

或使用 VS Code 插件: `hediet.vscode-drawio`
