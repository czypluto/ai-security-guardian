---
name: ignore-false-positives
description: 忽略已知误报：PID 284 Secure System、wpscloudsvr 等
# 触发词刻意收窄。
# 原来含 "scan" / "扫描" / "检查" / "威胁" —— 这些是**任何**安全查询都会出现的词，
# 而 match_triggers 取第一个命中的技能，于是「扫描网络」会命中本技能而不是
# network_scan，「勒索软件检查」也会。这个技能只应在用户明确抱怨误报时激活。
triggers:
  - "误报"
  - "false positive"
  - "不是威胁"
  - "判断错了"
  - "忽略了"
  - "误判"
---


# 忽略误报规则

## 已知误报进程 — 扫描时自动忽略
以下进程已被确认为系统/正规软件，**在 scan_processes 结果中直接忽略，不算作威胁**：

| 进程 | 原因 |
|------|------|
| PID 284（空名称/unknown路径） | Windows Secure System 内核进程，正常无 exe 路径 |
| wpscloudsvr.exe（端口 11111） | WPS 云服务，正常行为 |

## 规则
- scan_processes 后，若仅命中上述进程，直接报告「无威胁」
- 若同时命中其他可疑进程，正常报告但**排除**上述两项
- 安全摘要/风险判断中不因此类误报提高风险等级
