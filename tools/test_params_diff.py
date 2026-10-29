#!/usr/bin/env python3
"""tools/params_diff.py：两种文件格式、容差、元信息差异、退出码。"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import params_diff as P  # noqa: E402

with tempfile.TemporaryDirectory() as t:
    T = pathlib.Path(t)
    (T / "a.txt").write_text("# schema_hash = 0000ABCD\n# fw_rev = c3b7dfd\nkp = 0.08\nki = 1\nold = 3\n", encoding="utf-8")
    (T / "b.txt").write_text("# schema_hash = 0000ABCD\n# fw_rev = c3b7dfd+改动\nkp = 0.0800000001\nki = 2\nnew = 4\n", encoding="utf-8")
    (T / "c.json").write_text(json.dumps({"name": "x", "values": {"kp": 0.08, "ki": 1, "old": 3}}), encoding="utf-8")
    d = P.diff(P.load(T / "a.txt"), P.load(T / "b.txt"))
    assert d["changed"] == [("ki", 1.0, 2.0)], d                     # kp 在容差内
    assert d["only_a"] == ["old"] and d["only_b"] == ["new"]
    assert d["meta"] == {"fw_rev": ("c3b7dfd", "c3b7dfd+改动")}
    out = P.render(d, "a", "b")
    assert "~ ki: 1 → 2" in out and "fw_rev 不同" in out and "共 3 处" in out
    assert P.main([str(T / "a.txt"), str(T / "c.json")]) == 0         # 快照 json 与回读 txt 可互比（json 无元信息不算差异）
    assert P.main([str(T / "a.txt"), str(T / "b.txt")]) == 1
    (T / "bad.txt").write_text("这不是参数\n", encoding="utf-8")
    assert P.main([str(T / "a.txt"), str(T / "bad.txt")]) == 2
print("test_params_diff: 通过")
