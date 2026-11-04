#!/usr/bin/env python3
"""tools/check_reason_codes.py 的测试（#164）：合成侧车树，缺码失败、全在通过、只在 tests/ 里的码不算、表文件缺失 rc=2。"""
import io
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_reason_codes as crc  # noqa: E402


def tree(d: pathlib.Path):
    p = d / "app/sidecar/dzbench/agent"
    p.mkdir(parents=True)
    (p / "reason_codes.py").write_text('from .iterate import X_ZH\nSTOP_ZH = {"stop_a": "停"}\n', "utf-8")
    (p / "iterate.py").write_text('X_ZH = {"inv_b": "无效"}\n', "utf-8")
    (p.parent / "srv.py").write_text('def f(e):\n    e({"type": "link.state", "reason": "resume_x", "causes": ["c_one", "说明"]})\n'
                                     '    raise E("k", extra={"stop_reason": "sr"})\n', "utf-8")
    (p.parent / "tests").mkdir()
    (p.parent / "tests/test_x.py").write_text('X = {"reason": "test_only"}\n', "utf-8")
    return {"stop_a", "inv_b", "resume_x", "c_one", "sr"}


def main():
    with tempfile.TemporaryDirectory(prefix="dz_trc_") as d:
        r = pathlib.Path(d); want = tree(r); tab = r / "t.json"
        codes, _, _ = crc.collect(r / "app/sidecar")
        assert set(codes) == want, codes
        tab.write_text(json.dumps({c: {"message_zh": "中"} for c in want}), "utf-8")
        assert crc.run(r, tab, io.StringIO()) == 0
        tab.write_text(json.dumps({c: {"zh": "中"} for c in want - {"resume_x"}}), "utf-8")
        o = io.StringIO()
        assert crc.run(r, tab, o) == 1 and "resume_x" in o.getvalue() and "不在原因表" in o.getvalue()
        try:
            crc.run(r, r / "nope.json", io.StringIO()); raise AssertionError("应 exit 2")
        except SystemExit as e:
            assert e.code == 2
    print("test_check_reason_codes 通过")


if __name__ == "__main__":
    main()
