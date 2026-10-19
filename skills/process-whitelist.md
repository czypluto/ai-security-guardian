---
name: process-whitelist
description: 进程扫描白名单：自动跳过 Windows 系统核心进程，避免误报骚扰
triggers:
  - "白名单"
  - "whitelist"
  - "忽略进程"
  - "加白"
  - "扫描进程"
# 注：不再包含「可疑进程」—— 它与 process-check 的技能重复，而 match_triggers
# 取第一个命中者，重复会让「激活了哪个技能」取决于字典序。
---

# Process Whitelist Skill

当用户要求扫描进程或分析可疑进程时，自动应用以下白名单规则。

## 白名单进程（始终忽略，不报告为可疑）

以下 Windows 系统核心进程在扫描时自动跳过：

| 进程名 | 原因 |
|--------|------|
| Secure System | Windows 内核安全进程，受保护 |
| System | Windows 系统进程 |
| System Idle Process | CPU 空闲进程 |
| svchost.exe | Windows 服务宿主 |
| csrss.exe | 客户端服务器运行时 |
| wininit.exe | Windows 启动进程 |
| services.exe | 服务控制管理器 |
| lsass.exe | 本地安全认证 |
| winlogon.exe | Windows 登录 |
| spoolsv.exe | 打印后台程序 |
| smss.exe | 会话管理器 |
| RuntimeBroker.exe | 运行时代理 |
| SearchIndexer.exe | 搜索索引器 |
| ShellExperienceHost.exe | Shell 体验宿主 |
| DasHost.exe | 设备关联服务 |

## 行为规则

1. scan_processes 返回结果后，先过滤白名单中的进程
2. 只报告非白名单进程的可疑发现
3. 如果用户问"为什么某进程没报告"，说明它在白名单中
4. 用户可通过"添加白名单 [进程名]"添加新条目
5. 用户可通过"白名单列表"查看当前白名单
6. 用户可通过"移除白名单 [进程名]"删除条目

## 动态白名单管理

- 在回复中维护当前白名单状态
- 新增的白名单条目仅对当前会话有效
- 系统核心进程建议永久保留在白名单中