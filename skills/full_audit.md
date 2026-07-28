---
name: full-audit
description: Full system security audit — network + processes + firewall + logs
triggers:
  - "全面扫描"
  - "安全审计"
  - "full audit"
  - "audit my system"
  - "检查系统安全"
---

# Full System Security Audit

Perform a complete security audit of the Windows system.

## Steps

Execute these tools in order and aggregate results:

1. **check_firewall** — Verify Windows Firewall and Defender status
2. **scan_network** — Scan all active connections for suspicious IPs/ports
3. **scan_processes** — Find suspicious or malicious processes
4. **read_security_logs** — Read recent security events (last 30 min)
5. **security_summary** — Get risk level and event summary
6. **get_system_state** — Check CPU, memory, disk usage
7. **get_listening_ports** — List all open listening ports

## Output Format

```
=== Security Audit Report ===

[Firewall]
- Windows Firewall: ON/OFF
- Defender: ACTIVE/INACTIVE

[Network]
- Active connections: N
- Suspicious IPs: N
- Network status: safe/suspicious/under_attack

[Processes]
- Suspicious processes: N
- High CPU processes: N

[Security Events]
- Total events: N
- Failed logins: N
- Risk level: low/medium/high

[System Resources]
- CPU: X%
- Memory: X%
- Disk: X%

[Open Ports]
- Port list

[Verdict]
- Overall security level
- Actionable recommendations
```
