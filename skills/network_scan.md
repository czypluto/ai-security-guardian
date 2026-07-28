---
name: network-scan
description: Deep network analysis — connections, ports, suspicious endpoints
triggers:
  - "扫描网络"
  - "网络检查"
  - "network scan"
  - "check network"
  - "看看网络"
---

# Network Threat Analysis

Deep network inspection for threat detection.

## Steps

1. **scan_network** — Full connection scan with suspicious IP/port detection
2. **get_listening_ports** — List all open listening ports
3. **run_command** — `netstat -ano | findstr ESTABLISHED` for raw connection data
4. If suspicious IPs found: analyze each with **run_command** `nslookup <IP>`

## Output Format

```
=== Network Analysis ===

[Overview]
- Active connections: N
- Listening ports: N
- Suspicious endpoints: N

[Suspicious Details]
For each suspicious endpoint:
  - IP:Port — Reason (e.g., "Metasploit port 4444")
  - Process: name
  - Severity: high/medium/low

[Recommendations]
- If C2 ports detected: investigate process, consider blocking
- If high-frequency connections: possible data exfiltration
- If unknown listening ports: audit the service
```
