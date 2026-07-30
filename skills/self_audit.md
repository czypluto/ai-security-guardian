---
name: self-audit
description: Runtime self-integrity verification for the AI Security Guardian
triggers:
  - "self audit"
  - "self check"
  - "check yourself"
  - "are you compromised"
  - "verify integrity"
  - "integrity check"
  - "自查"
  - "自我检查"
  - "你被篡改了吗"
  - "自审计"
---

# Self-Audit Skill — AI 安全管家运行时自审计

## 何时触发

当用户询问以下问题时，自动执行自审计：
- "你安全吗" / "你被黑了吗" / "你被篡改了吗"
- "自查" / "自我检查" / "自审计"
- "check yourself" / "are you compromised" / "verify integrity"
- 定期维护命令（每天首次对话时建议执行）

## 执行流程

### Step 1: 快速检查 (always first)

调用 `self_audit` 工具，运行完整 7 层自审计：

1. **文件完整性** — 验证所有 .py 文件 SHA256 哈希值
2. **依赖审计** — 检查 pip 包是否有可疑/typosquatting
3. **配置守卫** — 检查 API Key 是否泄露、MCP 是否被重定向
4. **运行时完整性** — Python 解释器位置、可疑 DLL、环境变量
5. **代码注入扫描** — 搜索混淆/注入模式（base64 exec 等）
6. **网络自查** — 守护进程自身的外连是否可疑
7. **沙箱完整性** — 验证 6 层沙箱每一层实际工作

### Step 2: 分析结果

- **Score ≥ 80**: 系统完整，告知用户一切正常
- **Score 50-79**: 存在警告，逐项说明问题和建议修复
- **Score < 50**: 严重问题！建议用户立即：
  1. 断开网络
  2. 从 GitHub 重新 clone 项目
  3. 检查 API Key 是否泄露（如有泄露立即重置）
  4. 运行 `python agent/self_audit.py --full --json` 导出完整报告

### Step 3: 针对性修复建议

根据发现的问题类型给出具体建议：

| 问题类型 | 建议 |
|---------|------|
| 文件被修改 | `git diff` 查看变更，`git checkout -- <file>` 恢复 |
| 可疑 pip 包 | `pip uninstall <package>` 立即卸载 |
| 配置文件被篡改 | 检查 base_url 是否指向非官方地址 |
| 可疑网络连接 | `netstat -ano` 查 PID，终止可疑进程 |
| 沙箱层失效 | 检查 Windows Job Object 权限，重启程序 |

## 安全原则

- **fail-closed**: 任何检查失败都应视为潜在入侵
- **不自动修复**: 向用户报告，由用户决定如何处理
- **不访问外部**: 自审计完全本地执行，不产生网络请求
- **定期执行**: 建议每次启动时自动执行 quick_check

## 内置自审计工具

本技能可使用以下工具：

- `self_audit` — 完整 7 层审计（~3-5秒）
- `self_check_network` — 仅网络自查（~1秒）
- `self_verify_files` — 仅文件哈希验证（~1秒）
