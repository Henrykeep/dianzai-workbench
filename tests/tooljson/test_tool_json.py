"""Unified --json envelope + exit codes (tools/tooljson.py) for gen_link / pin_check / selfcheck / tunegate.

Same input -> byte-identical stdout (run twice, and from a different cwd); outside `details` there are no absolute
paths or timings; every non-zero exit carries exactly the reason code whose registered exit code it is.
"""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import tooljson as T  # noqa: E402

ENV = {k: v for k, v in os.environ.items() if not k.startswith("DZ_LLM_")} | {"PYTHONUTF8": "1"}
BOARD = next(p for p in sorted((ROOT / "boards").glob("*/board.yaml")))
APP = next(p for p in sorted((ROOT / "apps").glob("*/app.yaml")) if "\nlink:" in p.read_text("utf-8"))


def run(tool, *args, cwd=ROOT, env=None):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / tool), *map(str, args)], cwd=str(cwd), capture_output=True,
                       env=env or ENV, timeout=900)
    return r.returncode, r.stdout


def check_env(rc, out, tool):
    assert b"\r\n" not in out and out.isascii(), out[:200]
    d = json.loads(out)
    assert d["tool"] == tool and d["stage"] in T.STAGES and d["exit_code"] == rc
    assert set(d) >= {"state", "blocks", "errors", "details"}
    assert out.decode() == T.dumps(d), "keys not sorted / not canonical"
    if rc:
        assert d["errors"] and T.CODES[d["errors"][0]["reason_code"]][0] == rc, d["errors"]
        assert d["state"] == ("confirm_required" if rc == 5 else "error")
    else:
        assert d["state"] == "ok" and not d["errors"]
    pub = json.dumps({k: v for k, v in d.items() if k not in ("details", "errors")}
                     | {"errors": [{k: v for k, v in e.items() if k != "details"} for e in d["errors"]]})
    for p in (str(ROOT), str(pathlib.Path.home()), "/tmp", "C:\\\\"):
        assert p not in pub, f"absolute path outside details: {p}"
    for e in d["errors"]:
        assert set(e) >= {"reason_code", "fix_action", "message_zh"}
    return d


def same_twice(tool, *args, tmp=None):
    a, b = run(tool, *args), run(tool, *args, cwd=tmp or ROOT)
    assert a[0] == b[0]
    strip = lambda o: json.dumps({k: v for k, v in json.loads(o).items() if k != "details"}, sort_keys=True)
    assert a[1] == run(tool, *args)[1], "not byte-identical across runs"
    assert strip(a[1]) == strip(b[1]), "differs with cwd"
    return a


def test_codes_table():
    assert {c for c, (rc, _) in T.CODES.items()} and all(rc in (1, 2, 3, 4, 5) or rc >= 10 for rc, _ in T.CODES.values())
    for need in (2, 3, 4, 5, 10):
        assert need in {rc for rc, _ in T.CODES.values()}


def test_pin_check(tmp_path):
    rc, out = same_twice("pin_check.py", BOARD, "--json", tmp=tmp_path)
    d = check_env(rc, out, "pin_check")
    assert rc in (0, 1) and d["blocks"][0]["type"] == "kv"
    bad = tmp_path / "board.yaml"
    bad.write_text("- not a mapping\n", encoding="utf-8")
    check_env(*run("pin_check.py", bad, "--json"), "pin_check")
    rc, out = run("pin_check.py", tmp_path / "nope.yaml", "--json")
    assert rc == 2 and check_env(rc, out, "pin_check")["errors"][0]["reason_code"] == "tool_bad_arg"
    rc, _ = run("pin_check.py", BOARD)
    assert rc in (0, 1)


def test_gen_link(tmp_path):
    out_dir = tmp_path / "o"
    rc, out = same_twice("gen_link.py", APP, "-o", out_dir, "--json", tmp=tmp_path)
    d = check_env(rc, out, "gen_link")
    assert rc == 5 and d["preview"]["token"] and not out_dir.exists(), "must not write before confirm"
    rc, out = run("gen_link.py", APP, "-o", out_dir, "--json", "--yes")
    assert rc == 0 and check_env(rc, out, "gen_link")["details"]["wrote"] is True
    assert sorted(p.name for p in out_dir.iterdir()) == ["link_gen.c", "link_gen.h", "link_schema.json"]
    rc, out = run("gen_link.py", APP, "-o", out_dir, "--json")
    assert rc == 0, "unchanged output needs no confirmation"
    rc, out = run("gen_link.py", "--json")
    assert rc == 2 and check_env(rc, out, "gen_link")["errors"][0]["reason_code"] == "tool_bad_arg"
    bad = tmp_path / "bad.yaml"
    bad.write_text("link:\n  telemetry: {id: 2, fields: [{name: x, type: nosuch}]}\n  params: []\n", encoding="utf-8")
    rc, out = run("gen_link.py", bad, "-o", out_dir, "--json")
    assert rc == 1 and check_env(rc, out, "gen_link")["errors"][0]["reason_code"] == "link_spec_invalid"


def test_selfcheck(tmp_path):
    rc, out = same_twice("selfcheck.py", "--json", tmp=tmp_path)
    d = check_env(rc, out, "selfcheck")
    assert d["rc"] == rc and all(i["status"] in ("ok", "missing", "invalid", "unchecked") for i in d["items"])


def test_tunegate(tmp_path):
    env = ENV | {"TUNEGATE_SOURCE": "randplant"}
    a = run("tunegate.py", "--seed", "7", "--json", env=env)
    b = run("tunegate.py", "--seed", "7", "--json", env=env, cwd=tmp_path)
    d = check_env(*a, "tunegate")
    strip = lambda o: json.dumps({k: v for k, v in json.loads(o).items() if k != "details"}, sort_keys=True)
    assert a[0] == b[0] and strip(a[1]) == strip(b[1])
    assert a[0] in (0, 1) and d["blocks"][1]["rows"][0][0] == 7
    rc, out = run("tunegate.py", "--n", "notanint", "--json", env=env)
    assert rc == 2 and check_env(rc, out, "tunegate")["errors"][0]["reason_code"] == "tool_bad_arg"
    rc, out = run("tunegate.py", "--seed", "7", "--json", env=ENV | {"TUNEGATE_SOURCE": "standin"})
    assert rc == 1 and "tune_standin" in [e["reason_code"] for e in check_env(rc, out, "tunegate")["errors"]]
