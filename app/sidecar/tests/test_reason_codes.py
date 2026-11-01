"""#139：后端每个迭代原因码都在 docs/dev/reason_codes.json，zh 非空，文件与后端枚举同步。"""
import json
import pathlib
import re

from dzbench.agent import iterate as I
from dzbench.agent.reason_codes import table

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_every_backend_code_listed():
    j = json.loads((ROOT / "docs/dev/reason_codes.json").read_text("utf-8"))
    assert j == table()
    src = pathlib.Path(I.__file__).read_text("utf-8")
    codes = set(re.findall(r'_stopped\("(\w+)"', src)) | set(I.INVALID_ZH) | set(I.ACK_ZH)
    codes |= set(re.findall(r'"estop" if e\.code == "estop" else "(\w+)"', src))
    missing = sorted(c for c in codes if c not in j or not j[c]["zh"].strip())
    assert not missing, missing
    assert all(v["kind"] in ("round", "abort", "stop", "diverge", "blocker") for v in j.values())


def test_every_link_resume_code_has_message_zh():
    """#164：fix-r9c 发出的每个连接 / 恢复原因码（link.state reason、down_reason、LinkError(code, …, {"reason": …})、
    停止原因 plant_unresponsive）都在表里且带非空 message_zh；有修复动作的 fix_action 与发出的一致。"""
    from dzbench import linkstate, session
    j = json.loads((ROOT / "docs/dev/reason_codes.json").read_text("utf-8"))
    src = pathlib.Path(session.__file__).read_text("utf-8")
    emitted = {"resume_no_response", "resuming", "plant_unresponsive", "estop_latched_ident_deferred", "fw_estop_unsafe"}
    emitted |= set(linkstate.REASON_ZH)
    emitted |= set(re.findall(r'self\.down_reason = "(\w+)"', src))
    emitted |= set(re.findall(r'"port_ambiguous" if why == "ambiguous" else "(\w+)"', src))
    emitted |= {session.Session.RESUME_NO_RESPONSE}
    # 带 message_zh 抛出的 LinkError：reason 字段就是原因码
    emitted |= {m for m in re.findall(r'\{"reason": "(\w+)", "message_zh"', src)} & set(j)
    assert {"port_not_found", "port_ambiguous"} <= emitted
    bad = sorted(c for c in emitted if c not in j or not (j[c].get("message_zh") or "").strip())
    assert not bad, f"这些原因码没进 reason_codes.json 或缺 message_zh：{bad}"
    for c, zh in linkstate.REASON_ZH.items():
        assert j[c]["message_zh"] == zh, c                 # link.state 的中文与表一致
    assert j["resume_no_response"]["fix_action"] == "reconnect"
    assert j["resume_no_response"]["message_zh"] == session.Session.RESUME_NO_RESPONSE_ZH
    for c, fa in re.findall(r'LinkError\("(\w+)",[^\n]*\n?[^\n]*?"(estop_clear|reflash|reconnect)", \{"reason"', src):
        if c in j and "fix_action" in j[c]:
            assert j[c]["fix_action"] == fa, (c, fa)
