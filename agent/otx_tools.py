"""
AlienVault OTX — Free threat intelligence.
API: https://otx.alienvault.com/api/v1
No API key required for basic indicator queries.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger("Guardian.OTX")

OTX_BASE = "https://otx.alienvault.com/api/v1"
CACHE_TTL = 300  # 5 minutes

_cache: dict[str, tuple[float, dict]] = {}


def _get_cached(url: str) -> Optional[dict]:
    if url in _cache:
        ts, data = _cache[url]
        if time.time() - ts < CACHE_TTL:
            return data
    return None


def _set_cache(url: str, data: dict):
    _cache[url] = (time.time(), data)


def _otx_request(endpoint: str) -> dict:
    """Make a rate-limited request to OTX API."""
    url = f"{OTX_BASE}{endpoint}"
    cached = _get_cached(url)
    if cached:
        logger.debug(f"OTX cache hit: {endpoint}")
        return cached

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AI-Security-Guardian/2.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            _set_cache(url, data)
            return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"error": "not_found", "message": "No data in OTX"}
        if e.code == 429:
            return {"error": "rate_limited", "message": "Try again later"}
        return {"error": f"http_{e.code}", "message": str(e)}
    except Exception as e:
        return {"error": "request_failed", "message": str(e)}


# ================================================================
#  Tool handlers
# ================================================================

def threat_check_ip(ip: str) -> dict:
    """Query OTX for IP reputation."""
    data = _otx_request(f"/indicators/IPv4/{ip}/general")
    if "error" in data:
        return data

    pulses = data.get("pulse_info", {}).get("pulses", [])
    return {
        "ip": ip,
        "reputation": data.get("reputation", 0),
        "pulse_count": data.get("pulse_info", {}).get("count", 0),
        "country": data.get("country_name", "unknown"),
        "city": data.get("city", "unknown"),
        "malicious": _is_malicious(data),
        "threat_tags": _extract_tags(pulses)[:10],
        "recent_pulses": _summarize_pulses(pulses, 3),
    }


def threat_check_domain(domain: str) -> dict:
    """Query OTX for domain reputation."""
    data = _otx_request(f"/indicators/domain/{domain}/general")
    if "error" in data:
        return data

    pulses = data.get("pulse_info", {}).get("pulses", [])
    return {
        "domain": domain,
        "reputation": data.get("reputation", 0),
        "pulse_count": data.get("pulse_info", {}).get("count", 0),
        "alexa_rank": data.get("alexa", "unknown"),
        "whois": data.get("whois", "")[:200],
        "malicious": _is_malicious(data),
        "threat_tags": _extract_tags(pulses)[:10],
        "recent_pulses": _summarize_pulses(pulses, 3),
    }


def threat_check_hash(file_hash: str) -> dict:
    """Query OTX for file hash reputation."""
    data = _otx_request(f"/indicators/file/{file_hash}/general")
    if "error" in data:
        return data

    pulses = data.get("pulse_info", {}).get("pulses", [])
    return {
        "hash": file_hash,
        "reputation": data.get("reputation", 0),
        "pulse_count": data.get("pulse_info", {}).get("count", 0),
        "malware_name": data.get("malware", "unknown"),
        "file_type": data.get("type", "unknown"),
        "malicious": _is_malicious(data),
        "threat_tags": _extract_tags(pulses)[:10],
        "recent_pulses": _summarize_pulses(pulses, 3),
    }


def threat_pulse_search(query: str) -> dict:
    """Search OTX threat pulses by keyword."""
    data = _otx_request(f"/pulses/subscribed?q={urllib.parse.quote(query)}&limit=5")
    if "error" in data:
        return data

    results = data.get("results", [])
    return {
        "query": query,
        "total_results": data.get("count", 0),
        "pulses": [
            {
                "name": p.get("name", ""),
                "description": p.get("description", "")[:200],
                "created": p.get("created", ""),
                "tags": [t.get("name") for t in p.get("tags", [])],
            }
            for p in results[:5]
        ],
    }


# ================================================================
#  Helpers
# ================================================================

def _is_malicious(data: dict) -> bool:
    """Determine if indicator is considered malicious."""
    reputation = data.get("reputation", 0)
    pulse_count = data.get("pulse_info", {}).get("count", 0)
    return reputation is not None and reputation < 0 and pulse_count > 0


def _extract_tags(pulses: list) -> list[str]:
    tags = set()
    for p in pulses[:20]:
        for t in p.get("tags", [])[:5]:
            if isinstance(t, dict):
                tags.add(t.get("name", ""))
            else:
                tags.add(str(t))
    return sorted(tags)


def _summarize_pulses(pulses: list, n: int) -> list[dict]:
    result = []
    for p in pulses[:n]:
        result.append({
            "name": p.get("name", ""),
            "description": p.get("description", "")[:150],
            "created": p.get("created", ""),
            "adversary": p.get("adversary", ""),
        })
    return result


import urllib.parse
