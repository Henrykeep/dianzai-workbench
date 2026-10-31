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
