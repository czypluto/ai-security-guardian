---
name: ransomware-check
description: 勒索软件专项检测 — 检查卷影副本、可疑加密进程、最新勒索情报
triggers:
  - "勒索"
  - "ransomware"
  - "勒索软件"
  - "加密病毒"
---

# Ransomware Detection Checklist

Execute these steps in order:

1. **scan_processes** — Look for processes with names like vssadmin, cipher, wbadmin, or high disk I/O
2. **run_command** command="vssadmin list shadows" — Check if Volume Shadow Copies exist (ransomware deletes them)
3. **run_command** command="wmic shadowcopy list brief" — Verify shadow copy status
4. **threat_pulse_search** query="ransomware" — Get latest ransomware threat intelligence
5. **check_firewall** — Ensure firewall is blocking inbound SMB (port 445)

## If ransomware detected:
- Immediately disconnect from network
- Do NOT pay ransom
- Check for recent shadow copies for recovery
- Report to authorities (CERT, local police cyber unit)
