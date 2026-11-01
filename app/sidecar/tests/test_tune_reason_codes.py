"""#164：整定代码（tuning/、iterate 停止）能发出的每个原因码都在界面读的 docs/dev/reason_codes.json 里，且有 message_zh / zh。
码从源码里收集（"code": "…"、cat/stop_reason 取值字典、reason 常量、_stopped("…")），不手写清单。"""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "app" / "sidecar" / "dzbench"


def emitted() -> set[str]:
    from dzbench.tuning import autotune as AT
    codes = set(AT.STOP_ZH) | set(AT.CAUSE_ZH) | {"unconfirmed", "max_rounds"}
    for f in (SRC / "tuning").glob("*.py"):
        t = f.read_text("utf-8")
        codes |= set(re.findall(r'"code":\s*"([a-z_]+)"', t))
        codes |= set(re.findall(r'"reason":\s*"([a-z_]+)"', t))
    codes |= set(re.findall(r'_stopped\("([a-z_]+)"', (SRC / "agent" / "iterate.py").read_text("utf-8")))
    return codes


def test_every_tuning_code_in_ui_table_with_message():
    table = json.loads((ROOT / "docs" / "dev" / "reason_codes.json").read_text("utf-8"))
    codes = emitted()
    assert {"noise_amplified_saturation", "improvement_unconfirmed", "kept_initial", "max_rounds"} <= codes
    missing = sorted(c for c in codes if c not in table)
    assert not missing, missing
    for c in codes:
        e = table[c]
        assert (e.get("message_zh") or e.get("zh") or "").strip(), c
    for c in ("noise_amplified_saturation", "improvement_unconfirmed", "kept_initial", "max_rounds", "converged", "budget_exhausted"):
        assert table[c].get("message_zh"), c
