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



def test_find_by_hash_prefers_newest_of_same_hash(tmp_path, monkeypatch):
    """flaky 根因：同一应用编给多块板 → 同 hash 多份 link_schema.json（hash 不含 wd_timeout_ms）；
    以前按文件系统顺序取第一份，拿到旧固件的表 → threshold 读成 null，测试按 1000 ms 等，板子 1500 ms 才锁存。"""
    import json, os
    from dzbench import schema as SC
    base = {"hash": 0x1234, "telemetry": {"id": 2, "fields": [{"name": "y", "type": "f32"}]}, "params": []}
    old = tmp_path / "a-old-board" / "app" / "linkgen" / "link_schema.json"
    new = tmp_path / "b-host-sim" / "app" / "linkgen" / "link_schema.json"
    for f, d in ((old, base), (new, dict(base, wd_timeout_ms=2300))):
        f.parent.mkdir(parents=True); f.write_text(json.dumps(d), "utf-8")
    os.utime(old, (1e9, 1e9))
    monkeypatch.setattr(SC, "search_dirs", lambda: [tmp_path])
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
    assert df.check()[0]["reason"] == "data_file_missing" and "版本 2" in df.check()[0]["message_zh"]
    assert SV.link_roles() == () and "版本 2" in SV.role_hint_zh()
    assert df.main() == 1
