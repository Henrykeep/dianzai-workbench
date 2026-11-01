"""xintai-selfcheck.sh 入口：PYTHONPATH 置空；有依赖 → 0；缺依赖的 Python → 非 0、中文原因、无 Traceback。"""
import os
import pathlib
import subprocess
import json
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SH = ROOT / "xintai-selfcheck.sh"
sys.path.insert(0, str(ROOT / "tools"))
import selfcheck  # noqa: E402

WANT = 0 if selfcheck.has_selfcheck_data() else 3   # 侧车没有 selfcheck-data → 未完成（3），不算通过


def _run(py):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DZ_LLM_")}
    env.update(PYTHONPATH="", DZ_NOPAUSE="1", PYTHON=str(py))
    env.pop("PYTHONHOME", None)
    return subprocess.run([str(SH)], cwd=str(ROOT), env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=300)


def test_order_candidates():
    s = SH.read_text()
    assert ".venv/bin/python python3.12 python3.13 python3.11 python3 python" in s


def test_passes_with_deps():
    r = _run(sys.executable)
    assert r.returncode == WANT, r.stdout + r.stderr
    if WANT == 3:
        assert "[未检查]" in r.stdout and "自检未完成：1 项未检查" in r.stdout and "自检全部通过" not in r.stdout
    assert "Traceback" not in r.stdout + r.stderr


def test_fails_chinese_without_deps(tmp_path):
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "v")], check=True)
    r = _run(tmp_path / "v" / "bin" / "python")
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "缺少" in out and "[失败]" in out, out
    assert "Traceback" not in out, out


def test_json_statuses():
    r = subprocess.run([sys.executable, str(ROOT / "tools/selfcheck.py"), "--json"], capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=""), timeout=300)
    d = json.loads(r.stdout)
    assert r.returncode == d["rc"] == WANT
    st = {i["id"]: i["status"] for i in d["items"]}
    assert st["python_deps"] == st["roles"] == st["reason_codes"] == "ok"
    assert st["selfcheck_data"] == ("ok" if WANT == 0 else "unchecked")
    assert all(i["status"] in ("ok", "missing", "invalid", "unchecked") for i in d["items"])
    assert d["complete"] is (WANT == 0)


def test_summarize_codes():
    it = lambda s: {"status": s}
    assert selfcheck.summarize([it("ok"), it("ok")])[0] == 0
    rc, msg = selfcheck.summarize([it("ok"), it("unchecked"), it("unchecked")])
    assert rc == 3 and msg == "自检未完成：2 项未检查"
    assert selfcheck.summarize([it("missing"), it("unchecked")])[0] == 1
    assert selfcheck.summarize([it("invalid")])[0] == 1


def test_json_without_deps(tmp_path):
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "v")], check=True)
    r = subprocess.run([str(tmp_path / "v/bin/python"), str(ROOT / "tools/selfcheck.py"), "--json"],
                       capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=""), timeout=300)
    d = json.loads(r.stdout)
    assert r.returncode == 1 and d["items"][0]["status"] == "missing"
    assert [i["status"] for i in d["items"][1:]] == ["unchecked"] * 3


def test_cp1252_console_no_unicode_error():
    """app-windows 41273621192：cp1252 控制台下 selfcheck.py 打中文崩溃。两种输出都不能抛 UnicodeEncodeError。"""
    import json as _json
    import os as _os
    import pathlib as _pl
    import subprocess as _sp
    import sys as _sys
    tool = _pl.Path(__file__).resolve().parents[2] / "tools" / "selfcheck.py"
    env = dict(_os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
    for args in (["--json"], []):
        p = _sp.run([_sys.executable, str(tool), *args], capture_output=True, env=env, timeout=120)
        assert b"UnicodeEncodeError" not in p.stderr, p.stderr.decode("utf-8", "replace")
        assert p.returncode in (0, 1, 3)
        if args:
            d = _json.loads(p.stdout.decode("ascii"))
            assert d["rc"] == p.returncode
