"""#102：心跳 bit18 DZCTL_HB_SENSOR_SAT（dzctl 0.15.0）——到量程的一轮不算稳定；最后一轮到量程 → best=None。"""
import random

from dzbench.agent import iterate as I
from dzbench import session as S
from dzbench.stepproto import HB_SENSOR_SAT
from test_r9e import MockIO, PLAN


class SatIO(MockIO):
    def __init__(self, sat_from, **kw):
        super().__init__(**kw)
        self.sat_from, self.k = sat_from, 0

    def step(self, *a, **kw):
        r = dict(super().step(*a, **kw))
        self.k += 1
        r["sensor_sat"] = self.k >= self.sat_from
        return r


def test_bit18_decoded_and_old_firmware_unaffected():
    assert HB_SENSOR_SAT == 1 << 18
    assert "被控量到量程" in S.hb_status_dict(HB_SENSOR_SAT)["hb_flags"]
    assert "被控量到量程" not in S.hb_status_dict(1 << 17)["hb_flags"]       # 旧固件没有 bit18


def test_last_round_saturated_gives_null_best():
    io = SatIO(sat_from=random.Random(3).randint(2, 3), kp=1.0, ki=1.0)
    out = I.Iterator(io, PLAN, True, emit=lambda e: None, max_rounds=3).run()
    assert out["best"] is None and out["message_zh"] == "发散，未找到稳定参数" and out["sensor_sat"], out


def test_unsaturated_run_keeps_best():
    io = SatIO(sat_from=10**6, kp=1.0, ki=1.0)
    out = I.Iterator(io, PLAN, True, emit=lambda e: None, max_rounds=3).run()
    assert out["best"] is not None and not out["sensor_sat"]
