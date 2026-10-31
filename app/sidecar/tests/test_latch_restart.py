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


def test_role_hint_matches_gen_link_enum():
    """#136：no_roles 提示里的角色取值来自 gen_link.ROLES，提示里的例子要能过 gen_link.check。"""
    import importlib.util, pathlib, re
    from dzbench.agent.service import role_hint_zh, link_roles
    f = pathlib.Path(__file__).resolve().parents[3] / "tools" / "gen_link.py"
    spec = importlib.util.spec_from_file_location("gl_t", f); gl = importlib.util.module_from_spec(spec); spec.loader.exec_module(gl)
    assert link_roles() == tuple(gl.ROLES)
    h = role_hint_zh()
    assert "kp" not in h and all(r in h for r in gl.ROLES), h
    ex = re.search(r"role: (\w+)", h).group(1)
    p = {"name": "g", "type": "float", "default": 0.1, "min": 0, "max": 1, "role": ex}
    assert not [e for e in gl.check({}, [p]) if "role" in e], gl.check({}, [p])
    assert [e for e in gl.check({}, [dict(p, role="kp")]) if "role" in e]
