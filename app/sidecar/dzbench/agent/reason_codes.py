"""迭代原因码总表（#139，前端用）：单轮无效（round）、开始被拒 / 中止（abort）、停止 / 发散（stop / diverge）。

docs/dev/reason_codes.json 由 tools/gen_reason_codes.py 从这里生成；tests/test_reason_codes.py 校验后端每个原因码都在表里、zh 非空、文件是最新的。
"""
from __future__ import annotations

from .iterate import ACK_ZH, INVALID_ZH

STOP_ZH = {"pass": "连续 2 轮达标", "estop": "急停", "stopped": "人点了停止迭代", "budget_time": "时间预算用完",
           "budget_rounds": "轮数上限用完", "invalid": "连续 3 轮无效", "no_improve": "连续 3 轮没有改进",
           "unstable": "发散（超调过大）", "blocked": "所有方向都被拒绝或限幅挡住"}
DIVERGE = {"unstable"}


def table() -> dict:
    out = {}
    for k, zh in INVALID_ZH.items():
        out[k] = {"zh": zh, "kind": "round"}
    for k, zh in ACK_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "abort"})
    for k, zh in STOP_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "diverge" if k in DIVERGE else "stop"})
    return dict(sorted(out.items()))
