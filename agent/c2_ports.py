"""已知 C2 / 后门 / 暴露服务端口 —— **唯一来源**。

## 为什么单独成模块

同一份清单此前散在四处：
  1. `esp32_isolation.BLOCKED_PORTS`（自建集合）
  2. `self_audit.SUSPICIOUS_PORTS`（与 ① 元素完全相同的另一份）
  3. `esp32_isolation` 生成 PowerShell 防火墙规则的命令串里（第三份硬编码）
  4. `network_monitor.MALICIOUS_PORTS`（带标签的字典）

**安全关键的清单一旦重复，改一处漏三处就是漏检。** 而且第 4 份当时已经漏了
`8443` 和 `9999` —— 系统其他地方都把它们当 C2，只有网络监控不认。

## 两个集合刻意不同

`KNOWN_C2_PORTS` 是**检测面**：宽一点没关系，多报总比漏报好。
`GUARDIAN_BLOCKED_PORTS` 是**守护进程自身的 egress 阻断**：必须保守 ——
把 `6379 / 27017 / 3389` 这类也塞进去，会误伤自己正常要用的东西。

后者是前者的子集，这条关系由 `tests/agent/test_c2_ports.py` 钉住，
防止有人往阻断集里加了不在知识库里的端口（那时就该先想想为什么）。
"""
from __future__ import annotations

from typing import Iterable

# 端口 -> 说明。检测/告警用。
KNOWN_C2_PORTS: dict[int, str] = {
    1337: "常见后门",
    2323: "Telnet 替代",
    4443: "Metasploit",
    4444: "Metasploit Meterpreter",
    5555: "Android ADB",
    5900: "VNC",
    6379: "Redis（未授权）",
    6666: "IRC C2",
    6667: "IRC C2",
    6697: "IRC SSL",
    8080: "HTTP 代理/隧道",
    8443: "HTTPS 替代端口（常见 C2）",
    8888: "常见代理",
    9001: "Tor OR",
    9030: "Tor",
    9050: "Tor SOCKS",
    9150: "Tor Browser",
    9999: "常见后门",
    27017: "MongoDB（未授权）",
    31337: "Back Orifice",
    3389: "RDP（对外暴露）",
}

# 守护进程**自身**绝不该外联的端口：防火墙出站规则 + 自检用。
# 比 KNOWN_C2_PORTS 小，理由见模块 docstring。
GUARDIAN_BLOCKED_PORTS: frozenset[int] = frozenset({
    4444, 31337, 6666, 6667, 6697, 8080, 8443, 9001, 9999,
})


def csv(ports: Iterable[int] = None) -> str:
    """升序逗号串，给 PowerShell `-RemotePort` 用。

    升序是为了**生成的脚本可复现、便于 diff 审阅**：从集合导出时如果直接迭代，
    顺序随解释器哈希随机化而变，同一份规则每次生成的脚本文本都不一样。

    注意：`-RemotePort` 里端口的先后**对防火墙行为没有任何影响**，
    所以把原来的手写序改成升序只是文本变化，规则语义完全一致。
    """
    return ",".join(str(p) for p in sorted(GUARDIAN_BLOCKED_PORTS if ports is None else ports))
