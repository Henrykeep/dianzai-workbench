"""#146：控制台代码页是 cp1252（PYTHONIOENCODING=cp1252）时，所有 CLI 出口仍输出 UTF-8 中文、不崩。"""
import json
import os
import pathlib
import subprocess
import sys

SC = pathlib.Path(__file__).resolve().parents[1]


def _env():
    e = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8",)}
    e["PYTHONIOENCODING"] = "cp1252"
    e["PYTHONUTF8"] = "0"
    return e


def _check(r):
    assert b"UnicodeEncodeError" not in r.stderr, r.stderr.decode("utf-8", "replace")
    out = json.loads(r.stdout.decode("utf-8"))
    assert r.returncode == 0 and out["ok"] and "正常" in out["items"][0]["message_zh"]


def test_selfcheck_script_cp1252():
    _check(subprocess.run([sys.executable, "-I", str(SC / "selfcheck_data.py")], cwd="/", env=_env(), capture_output=True, timeout=60))


def test_module_selfcheck_data_cp1252():
    _check(subprocess.run([sys.executable, "-m", "dzbench", "selfcheck-data"], cwd=SC, env=_env(), capture_output=True, timeout=60))


def test_datafiles_main_cp1252():
    _check(subprocess.run([sys.executable, "-c", "import sys; from dzbench import datafiles; sys.exit(datafiles.main())"],
                          cwd=SC, env=_env(), capture_output=True, timeout=60))


def test_doctor_cp1252():
    r = subprocess.run([sys.executable, "-m", "dzbench", "--doctor"], cwd=SC, env=_env(), capture_output=True, timeout=120)
    assert b"UnicodeEncodeError" not in r.stderr and r.returncode in (0, 1)
    r.stdout.decode("utf-8")
