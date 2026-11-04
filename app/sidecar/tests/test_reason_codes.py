"""#139：后端每个迭代原因码（含整定结果卡的 tune 类：improvement_unconfirmed、kept_initial）都在 docs/dev/reason_codes.json，zh 非空，文件与后端枚举同步。"""
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
    assert all(v["kind"] in ("round", "abort", "stop", "diverge", "blocker", "tune", "misc") for v in j.values())
