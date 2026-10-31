"""心跳：侧车长持 session.lock（事件循环 / 长活）1.5 s 不能让上位机心跳断档 → 不急停；真掉线（停发 > 超时）照样急停。
看门狗按固件 dzctl_wd 语义建模（apps/include/link_app.h：dzctl_wd_init(1000)），阈值归固件。"""
import threading
import time

from dzbench.session import Session, estop_cause_dict

WD_TIMEOUT_MS = 1000                      # 固件 link_app.h 当前值


class Tr:
    def __init__(self):
        self.t = []

    def write(self, b):
        self.t.append(time.monotonic())


def _wd_expired(stamps, t0, t1):
    pts = [t0] + [x for x in stamps if t0 <= x <= t1] + [t1]
    return max(b - a for a, b in zip(pts, pts[1:])) * 1000 > WD_TIMEOUT_MS


def _session():
    s = Session(emit=lambda e: None)
    s.tr, s.schema_hash, s.host_hb = Tr(), 0x1234, True
    gen = s._gen
    threading.Thread(target=s._host_heartbeat, args=(gen,), daemon=True).start()
    return s


def test_host_stall_1500ms_does_not_starve_heartbeat():
    s = _session()
    time.sleep(0.3)
    t0 = time.monotonic()
    with s.lock:                                                  # 模拟侧车长活 / 事件循环卡 1.5 s
        time.sleep(1.5)
    t1 = time.monotonic()
    assert not _wd_expired(s.tr.t, t0, t1), "持锁 1.5 s 期间心跳断档超过看门狗阈值"
    assert s.hb_gap_max_ms < 3 * Session.HOST_HB_PERIOD_S * 1000
    assert WD_TIMEOUT_MS >= 3 * Session.HOST_HB_PERIOD_S * 1000    # 统筹者规则：超时 ≥ 3 × 心跳周期
    s._gen += 1


def test_true_host_loss_still_trips():
    s = _session()
    time.sleep(0.3)
    s.host_hb = False                                             # 真掉线：不再发心跳
    t0 = time.monotonic()
    time.sleep(1.3)
    assert _wd_expired(s.tr.t, t0, time.monotonic())
    s._gen += 1


def test_hb_timeout_cause_message_and_fix_action():
    d = estop_cause_dict(2, 5000, 1001.0)
    assert d["message_zh"] == "心跳超时 1001 ms" and d["fix_action"] == "estop_clear"


def test_heartbeat_cadence_about_250ms_while_lock_held():
    s = _session()
    time.sleep(0.3)
    with s.lock:
        n0 = len(s.tr.t)
        time.sleep(1.5)
        ts = s.tr.t[n0:]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    assert len(ts) >= 5 and max(gaps) < 0.4 and min(gaps) > 0.15, gaps
    s._gen += 1


def test_threshold_unknown_is_not_invented():
    d = estop_cause_dict(2, 5000, 1001.0)
    assert d["threshold_ms"] is None and "阈值" not in d["detail_zh"]   # #138：没报就整段不写
    assert estop_cause_dict(2, 5000, 1600.0, threshold_ms=1500)["threshold_ms"] == 1500


def test_latch_record_and_restored_message(tmp_path, monkeypatch):
    from dzbench import latch, progress
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path))
    es = estop_cause_dict(2, 5000, 1001.0, threshold_ms=1000)
    latch.set("sim:x", None, "firmware:hb_timeout", es["message_zh"], cause=es)
    rec = latch.get("sim:x", None)
    assert rec["reason"] == "hb_timeout" and rec["measured_ms"] == 1001 and rec["threshold_ms"] == 1000
    assert time.strptime(rec["latched_at"][:19], "%Y-%m-%dT%H:%M:%S")
    v = latch.restored_view(rec)
    hm = time.strftime("%H:%M", time.localtime(rec["t"]))
    assert v["message_zh"] == f"{hm} 心跳超时 1001 ms，已锁存" and v["restored"] is True and v["fix_action"] == "estop_clear"
    b = progress.blockers({"link": {"board": "connected"}, "estop": True, "estop_cause": v, "estop_reason": v["message_zh"]})
    e = next(x for x in b if x["code"] == "estop")
    assert e["message_zh"] == v["message_zh"] and e["restored"] is True and e["fix_action"] == "estop_clear"


def test_r9g_manual_estop_omits_ms_and_restored_fields(tmp_path, monkeypatch):
    from dzbench import latch
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path))
    latch.set("sim:m", None, "ui", "上位机发出急停指令")
    rec = latch.get("sim:m", None)
    assert rec["reason"] == "manual" and rec["reason_zh"] and "measured_ms" not in rec and "threshold_ms" not in rec
    v = latch.restored_view(rec)
    assert {"reason", "reason_zh", "latched_at", "restored", "fix_action"} <= v.keys() and v["restored"] is True
    assert "measured_ms" not in v and "threshold_ms" not in v and "value" not in v and "gap_ms" not in v
    es = estop_cause_dict(2, 1, 1700.0, threshold_ms=None)               # 握手没有 wd_timeout_ms → threshold_ms 为 null
    assert es["measured_ms"] == 1700 and es["threshold_ms"] is None and es["restored"] is False
