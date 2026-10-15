"""C2 端口清单的「唯一来源」约束。

背景：同一份清单曾在 4 处各存一份，其中两处是完全相同的集合、一处是 PowerShell
命令串里的硬编码、还有一份带标签的字典漏了 8443/9999。安全关键清单重复 =
改一处漏三处 = 漏检。这里的用例就是防止它再次分裂。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import c2_ports  # noqa: E402
from agent.c2_ports import GUARDIAN_BLOCKED_PORTS, KNOWN_C2_PORTS, csv  # noqa: E402


def test_both_sets_nonempty():
    assert KNOWN_C2_PORTS, "检测用端口知识库不能为空"
    assert GUARDIAN_BLOCKED_PORTS, "自身阻断集不能为空"


def test_blocked_is_subset_of_known():
    """自身阻断集必须是知识库的子集。

    往阻断集里加一个知识库中没有的端口，应当先想想：是知识库漏了，
    还是这个端口本来就不该出现在自身 egress 规则里。
    """
    extra = set(GUARDIAN_BLOCKED_PORTS) - set(KNOWN_C2_PORTS)
    assert not extra, f"阻断集里有知识库未收录的端口：{sorted(extra)}"


def test_known_ports_covers_the_ones_that_used_to_be_missing():
    """回归：network_monitor 的自建字典曾漏掉 8443 / 9999，
    而系统其它地方都把它们当 C2。统一后必须覆盖。"""
    assert 8443 in KNOWN_C2_PORTS
    assert 9999 in KNOWN_C2_PORTS


def test_csv_is_sorted_and_matches_blocked_set():
    out = csv()
    nums = [int(x) for x in out.split(",")]
    assert nums == sorted(nums), f"csv 必须升序，便于脚本 diff：{out}"
    assert set(nums) == set(GUARDIAN_BLOCKED_PORTS)


def test_csv_accepts_explicit_set():
    assert csv({9, 1, 5}) == "1,5,9"


def test_consumers_share_the_same_object():
    """回归：两处曾各存一份元素完全相同的集合。
    这里断言它们指向的是**同一个对象**，而不只是值相等 ——
    值相等挡不住下次有人「顺手复制一份」。"""
    from agent import self_audit

    assert self_audit.NetworkSelfCheck.SUSPICIOUS_PORTS is GUARDIAN_BLOCKED_PORTS


def test_network_monitor_uses_the_shared_dict():
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "pc_agent"))
    from network_monitor import NetworkMonitor

    assert NetworkMonitor.MALICIOUS_PORTS is KNOWN_C2_PORTS


def test_firewall_script_uses_canonical_csv():
    """回归：防火墙规则的端口串曾是硬编码字面量，
    改 c2_ports 对它没有任何影响。现在必须来自同一来源。"""
    import agent.esp32_isolation as m

    cls = next(getattr(m, n) for n in dir(m)
               if isinstance(getattr(m, n), type) and hasattr(getattr(m, n), "generate_rules_script"))
    script = cls.generate_rules_script()
    assert f"-RemotePort {csv()} `" in script, "生成的规则里应嵌入同一个 csv()"
    # 不应再出现任何硬编码的端口串
    assert "4444,31337" not in script
