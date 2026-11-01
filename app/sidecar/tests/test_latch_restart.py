"""estop_latch.json：侧车重启后心跳再报一次急停，不得把 t / latched_at 改写成重启时刻；只补缺字段，只有 clear() 重置。"""
import json
import time

from dzbench import latch, snapshots


def test_restart_keeps_original_latch_time(home):
    latch.set("COM7", None, "firmware:hb_timeout", "心跳超时", {"cause": "hb_timeout", "message_zh": "心跳超时 1600 ms"})
    p = snapshots.base_dir() / "estop_latch.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    t0 = time.time() - 3 * 3600                             # 把原始锁存时刻挪到 3 小时前，模拟侧车重启隔了很久
    la0 = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0))
    for r in d.values():
        r["t"], r["latched_at"] = t0, la0
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    hm0 = time.strftime("%H:%M", time.localtime(t0))
    # 侧车重启：再次心跳急停，带上新测到的字段
    latch.set("COM7", None, "firmware:hb_timeout", "心跳超时",
              {"cause": "hb_timeout", "measured_ms": 1600, "threshold_ms": 1500})
    rec = latch.get("COM7", None)
    assert rec["t"] == t0 and rec["latched_at"] == la0, rec
    assert rec["measured_ms"] == 1600 and rec["threshold_ms"] == 1500, rec
    assert latch.restored_view(rec)["message_zh"].startswith(hm0), rec
    latch.clear("COM7", None)
    latch.set("COM7", None, "manual", "手动急停")
    assert latch.get("COM7", None)["t"] > t0 + 3600


def test_hb_timeout_text_uses_handshake_threshold():
    """#138：阈值文案只用握手 wd_timeout_ms，不写死 1000；没报就不出现阈值字样。"""
    from dzbench.session import estop_cause_dict
    d = estop_cause_dict(2, 5000, 2412.0, threshold_ms=2300)
    assert d["threshold_ms"] == 2300 and "阈值 2300 ms" in d["detail_zh"] and "1000" not in d["detail_zh"] and "1500" not in d["detail_zh"], d
    n = estop_cause_dict(2, 5000, 1612.0, threshold_ms=None)
    assert "阈值" not in n["detail_zh"] and n["threshold_ms"] is None, n



def test_find_by_hash_same_hash_different_content_is_conflict(tmp_path, monkeypatch):
    """同一应用编给多块板 → 同 hash 多份 link_schema.json（hash 不含 wd_timeout_ms）。以前取第一份、后来取最新一份，
    两块板来回插时都可能拿到另一块板的表。现在两份内容不同 → SchemaConflict，一份都不取；内容相同的拷贝不算冲突。"""
    import json, os
    import pytest
    from dzbench import schema as SC
    base = {"hash": 0x1234, "telemetry": {"id": 2, "fields": [{"name": "y", "type": "f32"}]}, "params": []}
    old = tmp_path / "a-old-board" / "app" / "linkgen" / "link_schema.json"
    new = tmp_path / "b-host-sim" / "app" / "linkgen" / "link_schema.json"
    for f, d in ((old, base), (new, dict(base, wd_timeout_ms=2300))):
        f.parent.mkdir(parents=True); f.write_text(json.dumps(d), "utf-8")
    os.utime(old, (1e9, 1e9))
    monkeypatch.setattr(SC, "search_dirs", lambda: [tmp_path])
    with pytest.raises(SC.SchemaConflict) as ei:
        SC.find_by_hash(0x1234)
    assert sorted(ei.value.paths) == sorted([str(old), str(new)])
    old.write_text(json.dumps(dict(base, wd_timeout_ms=2300)), "utf-8")      # 同内容拷贝：不冲突
    assert SC.find_by_hash(0x1234).wd_timeout_ms == 2300


def test_roles_hint_list_equals_roles_json_codes():
    import json, pathlib
    from dzbench.agent import service as SV
    d = json.loads((pathlib.Path(__file__).resolve().parents[3] / "docs/dev/roles.json").read_text("utf-8"))
    codes = [r["code"] for r in d["roles"]]
    assert list(SV.link_roles()) == codes
    h = SV.role_hint_zh()
    assert [c for c in codes if f"{c}（" in h] == codes and "kp" not in h, h


def _datafiles_at(tmp_path, monkeypatch, content):
    from dzbench import datafiles
    if content is not None:
        f = tmp_path / "docs" / "dev" / "roles.json"; f.parent.mkdir(parents=True); f.write_text(content, "utf-8")
    monkeypatch.setattr(datafiles, "roots", lambda: [tmp_path])
    return datafiles


def test_roles_json_missing_is_blocker_and_cli_fails(tmp_path, monkeypatch, capsys):
    from dzbench import progress
    from dzbench.agent import service as SV
    df = _datafiles_at(tmp_path, monkeypatch, None)
    probs = df.check()
    assert probs and probs[0]["reason"] == "data_file_missing" and probs[0]["fix_action"] == "reinstall" and probs[0]["file"].endswith("roles.json")
    bl = progress.blockers({"data_missing": probs, "link": {"board": "connected"}})
    assert bl[0]["code"] == "data_file_missing" and bl[0]["fix_action"] == "reinstall" and "重新安装" in bl[0]["message_zh"]
    assert "没找到" in SV.role_hint_zh() and "role: " not in SV.role_hint_zh()
    assert df.main() == 1


def test_roles_json_unknown_version_rejected(tmp_path, monkeypatch):
    from dzbench.agent import service as SV
    df = _datafiles_at(tmp_path, monkeypatch, '{"schema_version": 2, "roles": [{"code": "P", "zh": "比例"}]}')
    assert df.check()[0]["reason"] == "data_file_missing" and "schema_version 是 2" in df.check()[0]["message_zh"]
    assert SV.link_roles() == () and "schema_version 是 2" in SV.role_hint_zh()
    assert df.main() == 1


def test_hello_data_tables_sha256_matches_file_bytes(tmp_path, monkeypatch):
    import hashlib, json, pathlib
    from dzbench import datafiles
    t = datafiles.tables()
    f = pathlib.Path(__file__).resolve().parents[3] / "docs/dev/roles.json"
    assert t["roles"]["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()
    assert t["roles"]["content"] == json.loads(f.read_text("utf-8"))
    rc = datafiles.find("reason_codes.json")
    assert (t["reason_codes"] is None) == (rc is None or bool(datafiles.load("reason_codes.json")[1]))
    _datafiles_at(tmp_path, monkeypatch, None)
    assert datafiles.tables() == {"roles": None, "reason_codes": None}


def test_selfcheck_standalone_script_from_other_cwd_without_pythonpath(tmp_path):
    import json, os, pathlib, subprocess, sys
    from dzbench import datafiles
    script = pathlib.Path(__file__).resolve().parents[1] / "selfcheck_data.py"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "DZBENCH_REPO")}
    r = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env, capture_output=True, timeout=60)
    out = json.loads(r.stdout.decode("utf-8"))
    assert r.returncode == 0 and out["ok"] and out == datafiles.report()
    assert all(set(i) == {"file", "status", "message_zh", "fix_action"} for i in out["items"])


def test_selfcheck_op_missing_has_no_command_line(tmp_path, monkeypatch):
    import asyncio
    from dzbench import server
    _datafiles_at(tmp_path, monkeypatch, None)
    sv = server.Server.__new__(server.Server)
    sv.session = None
    r = asyncio.run(sv._op({"op": "selfcheck_data"}))
    it = next(i for i in r["items"] if i["file"].endswith("roles.json"))
    assert not r["ok"] and it["status"] == "missing" and it["fix_action"] == "reinstall"
    assert "python" not in it["message_zh"] and "-m" not in it["message_zh"] and "『运行自检』" in it["message_zh"]
