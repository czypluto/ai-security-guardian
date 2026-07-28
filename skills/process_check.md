---
name: process-check
description: Process investigation — find suspicious processes, check resource usage
triggers:
  - "检查进程"
  - "可疑进程"
  - "process check"
  - "what's running"
  - "看看进程"
---

# Process Investigation

Scan for suspicious processes and resource abuse.

## Steps

1. **scan_processes** — Full process scan with suspicious name detection
2. **get_system_state** — Check CPU and memory utilization
3. For each suspicious process: use **run_command** `wmic process where ProcessId=<PID> get Name,ExecutablePath,CommandLine`
4. If CPU > 80%: use **run_command** `tasklist /v | findstr "<PID>"` for high-CPU processes

## Output Format

```
=== Process Investigation ===

[Overview]
- Total processes: N
- Suspicious: N
- High CPU: N

[Suspicious Processes]
For each:
  - Name | PID | CPU% | MEM%
  - Path: executable path
  - Reason: (matches known hacker tool name / high resource / ...)

[Recommendations]
- If mimikatz/nmap detected: immediate investigation needed
- If unknown high-CPU process: check if legitimate
- Consider terminating with: guardian "kill process <PID>"
```
