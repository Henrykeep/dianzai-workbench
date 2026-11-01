"""#144：随包数据文件每一份都必需。逐个文件 × 缺失 / 坏 JSON / 结构损坏（roles 再加版本不认识）→ ok:false、
该项 missing|invalid + fix_action reinstall、CLI 退出码非 0（独立脚本在拷贝出的安装布局里真跑）。"""
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
NAMES = ["roles.json", "reason_codes.json"]
CASES = {"missing": None, "bad_json": "{not json", "bad_shape": "{}", "not_object": "[1, 2]"}


def _layout(tmp_path, name, content):
    """仿安装目录：<tmp>/app/sidecar/{dzbench, selfcheck_data.py} + <tmp>/docs/dev/*.json（datafiles 按 parents[3] 找仓库根）。"""
    sc = tmp_path / "app" / "sidecar"
    shutil.copytree(ROOT / "app/sidecar/dzbench", sc / "dzbench", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "app/sidecar/selfcheck_data.py", sc / "selfcheck_data.py")
    dd = tmp_path / "docs" / "dev"
    dd.mkdir(parents=True)
    for n in NAMES:
        shutil.copy(ROOT / "docs/dev" / n, dd / n)
    if content is None:
        (dd / name).unlink()
    else:
        (dd / name).write_text(content, "utf-8")
    return sc / "selfcheck_data.py"


def _run(script, tmp_path, enc=None):
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("DZBENCH_REPO", "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8")}
    if enc:
        env["PYTHONIOENCODING"] = enc
    return subprocess.run([sys.executable, "-I", str(script)], cwd="/", env=env, capture_output=True, timeout=60)


def test_all_present_ok(tmp_path):
    r = _run(_layout(tmp_path, "roles.json", (ROOT / "docs/dev/roles.json").read_text("utf-8")), tmp_path)
    out = json.loads(r.stdout.decode("utf-8"))
    assert r.returncode == 0 and out["ok"] and [i["status"] for i in out["items"]] == ["ok", "ok"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("case", list(CASES))
def test_each_file_missing_or_corrupt_fails(tmp_path, name, case):
    r = _run(_layout(tmp_path, name, CASES[case]), tmp_path)
    out = json.loads(r.stdout.decode("utf-8"))
    assert r.returncode != 0 and out["ok"] is False
    it = next(i for i in out["items"] if i["file"].endswith(name))
    assert it["status"] == ("missing" if case == "missing" else "invalid")
    assert it["fix_action"] == "reinstall" and "重新安装" in it["message_zh"]
    other = next(i for i in out["items"] if not i["file"].endswith(name))
    assert other["status"] == "ok"


def test_roles_unknown_version(tmp_path):
    r = _run(_layout(tmp_path, "roles.json", '{"schema_version": 999, "roles": [{"code": "P"}]}'), tmp_path)
    out = json.loads(r.stdout.decode("utf-8"))
    assert r.returncode == 1 and "999" in out["items"][0]["message_zh"]


def test_reason_codes_missing_hello_table_null(tmp_path, monkeypatch):
    from dzbench import datafiles
    _layout(tmp_path, "reason_codes.json", None)
    monkeypatch.setattr(datafiles, "roots", lambda: [tmp_path])
    assert datafiles.tables()["reason_codes"] is None and datafiles.tables()["roles"] is not None
    assert [p["file"] for p in datafiles.check()] == ["docs/dev/reason_codes.json"]


@pytest.mark.parametrize("content,expect", [
    ("{not json", "不是合法 JSON（第 1 行第 2 列"),
    ("[1, 2]", "顶层应是 JSON 对象，实际是 list"),
    ('{"roles": ["a"]}', "缺 schema_version 字段"),
    ('{"schema_version": 9, "roles": ["a"]}', "schema_version 是 9，本地服务只认 1"),
    ('{"schema_version": 1}', "缺 roles 字段"),
    ('{"schema_version": 1, "roles": []}', "roles 列表是空的"),
    ('{"schema_version": 1, "roles": {}}', "roles 应是列表"),
])
def test_broken_roles_names_file_and_problem(tmp_path, monkeypatch, content, expect):
    """#150：坏的 roles.json → 消息里有文件完整路径和具体哪里不对；任何情况下都不出现“版本 None”。"""
    from dzbench import datafiles
    dd = tmp_path / datafiles.REL
    dd.mkdir(parents=True)
    (dd / "roles.json").write_text(content, "utf-8")
    monkeypatch.setattr(datafiles, "roots", lambda: [tmp_path])
    d, p = datafiles.load("roles.json")
    assert d is None and p["fix_action"] == "reinstall"
    assert str(dd / "roles.json") in p["message_zh"] and expect in p["message_zh"], p["message_zh"]
    assert "None" not in p["message_zh"]
