"""
Windows Defender + NVD Vulnerability Tools — agent/defender_tools.py

Provides virus scanning (Defender) and CVE vulnerability lookup (NIST NVD).
All free — Defender is built into Windows, NVD is a public US government API.
No API keys required.

Tools exposed:
  defender_status          — Real-time protection & engine health
  defender_quick_scan      — Quick scan critical areas
  defender_full_scan       — Full system scan (hours)
  defender_threat_list     — History of detected malware
  defender_update          — Update virus signatures
  cve_lookup               — Look up CVE by ID (CVE-2024-xxxx)
  cve_search               — Search CVEs by keyword

Security: Defender commands run via PowerShell with strict timeout and output
limits. No administrative actions beyond scanning are permitted.
"""
from __future__ import annotations

import json
import logging
import subprocess
import urllib.request
import urllib.error
import urllib.parse

logger = logging.getLogger("Guardian.Defender")

# ================================================================
#  Windows Defender (via PowerShell)
# ================================================================

def _ps(cmd: str, timeout: int = 60) -> dict:
    """Run a PowerShell command, return parsed result."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace",
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        return {
            "success": result.returncode == 0,
            "stdout": stdout[:4096],
            "stderr": stderr[:1024] if stderr else "",
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def defender_quick_scan() -> dict:
    """Trigger a Windows Defender quick scan."""
    r = _ps("Start-MpScan -ScanType QuickScan -ErrorAction SilentlyContinue; Write-Host 'Quick scan started'")
    r["message"] = "Quick scan started. Check status with defender_threat_list."
    return r


def defender_full_scan() -> dict:
    """Trigger a Windows Defender full scan."""
    r = _ps("Start-MpScan -ScanType FullScan -ErrorAction SilentlyContinue; Write-Host 'Full scan started'")
    r["message"] = "Full scan started. This may take hours. Check status later."
    return r


def defender_threat_list() -> dict:
    """List threats detected by Windows Defender."""
    ps_cmd = """
$threats = Get-MpThreat -ErrorAction SilentlyContinue | Select-Object ThreatID, ThreatName, SeverityID, DetectionTime, Action, ActionSuccess, Resources
if (-not $threats) { Write-Host '[]' } else { $threats | ConvertTo-Json -Depth 3 }
"""
    r = _ps(ps_cmd)
    try:
        threats = json.loads(r.get("stdout", "[]"))
        if not isinstance(threats, list):
            threats = [threats]
        return {
            "threat_count": len(threats),
            "threats": [
                {
                    "name": t.get("ThreatName", "unknown"),
                    "severity": _severity_label(t.get("SeverityID", 0)),
                    "detected": t.get("DetectionTime", ""),
                    "action": t.get("Action", "unknown"),
                    "success": t.get("ActionSuccess", False),
                    "files": t.get("Resources", [])[:3],
                }
                for t in threats[:20]
            ],
        }
    except json.JSONDecodeError:
        return {"threat_count": 0, "threats": [], "raw": r.get("stdout", "")[:500]}


def defender_status() -> dict:
    """Get Windows Defender configuration and health."""
    ps_cmd = """
$prefs = Get-MpPreference -ErrorAction SilentlyContinue
$status = Get-MpComputerStatus -ErrorAction SilentlyContinue
@{
    RealTimeProtectionEnabled = $prefs.DisableRealtimeMonitoring -eq $false
    AntivirusEnabled = $status.AntivirusEnabled
    AntispywareEnabled = $status.AntispywareEnabled
    BehaviorMonitorEnabled = $status.BehaviorMonitorEnabled
    IoavProtectionEnabled = $status.IoavProtectionEnabled
    OnAccessProtectionEnabled = $status.OnAccessProtectionEnabled
    LastQuickScan = $status.QuickScanEndTime
    LastFullScan = $status.FullScanEndTime
    SignatureVersion = $status.AntivirusSignatureVersion
    EngineVersion = $status.AntivirusEngineVersion
    NISSignatureVersion = $status.NISSignatureVersion
} | ConvertTo-Json
"""
    r = _ps(ps_cmd)
    try:
        return json.loads(r.get("stdout", "{}"))
    except json.JSONDecodeError:
        return {"error": "parse failed", "raw": r.get("stdout", "")}


def defender_update_signatures() -> dict:
    """Update Windows Defender virus signatures."""
    r = _ps("Update-MpSignature -ErrorAction SilentlyContinue; Write-Host 'Signature update triggered'")
    r["message"] = "Signature update triggered."
    return r


def _severity_label(severity_id: int) -> str:
    labels = {0: "unknown", 1: "low", 2: "medium", 3: "moderate",
              4: "high", 5: "severe"}
    return labels.get(severity_id, f"level_{severity_id}")


# ================================================================
#  NVD (National Vulnerability Database) — CVE Lookup
# ================================================================

NVD_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"


def nvd_cve_lookup(cve_id: str) -> dict:
    """Look up a CVE by ID (e.g., CVE-2024-1234)."""
    url = f"{NVD_BASE}?cveId={urllib.parse.quote(cve_id)}"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AI-Security-Guardian/2.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}

    vulns = data.get("vulnerabilities", [])
    if not vulns:
        return {"cve_id": cve_id, "found": False}

    cve = vulns[0].get("cve", {})
    descs = cve.get("descriptions", [])
    metrics = cve.get("metrics", {})

    # Severity
    cvss_v31 = metrics.get("cvssMetricV31", [{}])[0]
    cvss = cvss_v31.get("cvssData", {})
    severity = cvss_v31.get("baseSeverity", cvss.get("baseSeverity", "unknown"))
    score = cvss.get("baseScore", 0)

    # Description
    desc_en = next((d.get("value", "") for d in descs if d.get("lang") == "en"), "")

    return {
        "cve_id": cve_id,
        "found": True,
        "description": desc_en[:300],
        "severity": severity,
        "cvss_score": score,
        "published": cve.get("published", ""),
        "last_modified": cve.get("lastModified", ""),
        "exploitability_score": cvss_v31.get("exploitabilityScore", 0),
        "impact_score": cvss_v31.get("impactScore", 0),
        "vector": cvss.get("vectorString", ""),
        "references": [
            r.get("url", "") for r in cve.get("references", [])[:5]
        ],
    }


def nvd_cve_search(keyword: str, limit: int = 10) -> dict:
    """Search CVEs by keyword (e.g., 'Windows 11', 'Apache Log4j')."""
    url = f"{NVD_BASE}?keywordSearch={urllib.parse.quote(keyword)}&resultsPerPage={min(limit, 20)}"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AI-Security-Guardian/2.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

    results = []
    for vuln in data.get("vulnerabilities", [])[:limit]:
        cve = vuln.get("cve", {})
        cve_id = cve.get("id", "")
        descs = cve.get("descriptions", [])
        desc = next((d.get("value", "") for d in descs if d.get("lang") == "en"), "")
        cvss31 = cve.get("metrics", {}).get("cvssMetricV31", [{}])[0]
        results.append({
            "cve_id": cve_id,
            "description": desc[:200],
            "severity": cvss31.get("baseSeverity", "unknown"),
            "score": cvss31.get("cvssData", {}).get("baseScore", 0),
        })

    return {
        "keyword": keyword,
        "total_results": data.get("totalResults", 0),
        "results": results,
    }
