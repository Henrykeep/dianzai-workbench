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



def test_role_hint_reads_only_roles_json(tmp_path, monkeypatch):
    """#136：提示只读 docs/dev/roles.json；例子要能过 gen_link.check；kp 过不了。"""
    import importlib.util, json, pathlib, re
    from dzbench.agent import service as SV
    root = pathlib.Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("gl_t", root / "tools" / "gen_link.py"); gl = importlib.util.module_from_spec(spec); spec.loader.exec_module(gl)
    f = tmp_path / "docs" / "dev" / "roles.json"; f.parent.mkdir(parents=True)
    f.write_text(json.dumps(list(gl.ROLES)), "utf-8")
    monkeypatch.setattr(SV, "_roles_json_paths", lambda: [f])
    assert SV.link_roles() == tuple(gl.ROLES)
    h = SV.role_hint_zh()
    assert "kp" not in h and all(r in h for r in gl.ROLES), h
    ex = re.search(r"role: (\w+)", h).group(1)
    p = {"name": "g", "type": "float", "default": 0.1, "min": 0, "max": 1, "role": ex}
    assert not [e for e in gl.check({}, [p]) if "role" in e]
    assert [e for e in gl.check({}, [dict(p, role="kp")]) if "role" in e]


def test_role_hint_without_roles_json_says_so(tmp_path, monkeypatch):
    from dzbench.agent import service as SV
    monkeypatch.setattr(SV, "_roles_json_paths", lambda: [tmp_path / "nope.json"])
    h = SV.role_hint_zh()
    assert SV.link_roles() == () and "roles.json 没找到" in h and "role:" not in h.split("；")[1], h


def test_repo_roles_json_matches_gen_link_when_present():
    """roles.json 生成后（嵌入式开发-2 的 gen_link --emit-roles）必须和 ROLES 一致。"""
    import importlib.util, json, pathlib
    root = pathlib.Path(__file__).resolve().parents[3]
    f = root / "docs" / "dev" / "roles.json"
    spec = importlib.util.spec_from_file_location("gl_t2", root / "tools" / "gen_link.py"); gl = importlib.util.module_from_spec(spec); spec.loader.exec_module(gl)
    if f.exists():
        assert json.loads(f.read_text("utf-8")) == list(gl.ROLES)


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
