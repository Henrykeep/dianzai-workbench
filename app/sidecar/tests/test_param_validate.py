"""#40 / #24：参数写入校验。r7 misuse-ws.log 里的非法值（abc、空串、None、0x10、"1,5"、NaN、±Inf、越界）
一律 invalid_param（带 fix_action=params、message_zh、例子），不再 internal，也不再悄悄钳位。"""
import math

import pytest

from dzbench.schema import check_value
from dzbench.session import LinkError, Session

KP = {"name": "kp", "type": "f32", "min": 0.0, "max": 2.0}
AXIS = {"name": "imu_axis", "type": "u8", "min": 0, "max": 5}


@pytest.mark.parametrize("raw", ["abc", "", "  ", None, "0x10", "1,5", "1_0", True, "nan", "NaN", "inf", "-inf",
                                 float("nan"), math.inf, "1e30", "-1e30", 9, -0.1, [1], {"v": 1}])
def test_rejects(raw):
    with pytest.raises(LinkError) as e:
        check_value("kp", raw, KP)
    d = e.value.as_dict()
    assert d["code"] == "invalid_param" and d["fix_action"] == "params" and d["message_zh"] and d["name"] == "kp"
    assert "例如" in d["fix"]


@pytest.mark.parametrize("raw,v", [("0.5", 0.5), (" 1 ", 1.0), (2, 2.0), (0, 0.0), ("1e-3", 0.001), ("１", 1.0)])
def test_accepts(raw, v):
    assert check_value("kp", raw, KP) == v


def test_integer_param():
    assert check_value("imu_axis", "3", AXIS) == 3.0
    for bad in ("2.5", 6, -1):
        with pytest.raises(LinkError) as e:
            check_value("imu_axis", bad, AXIS)
        assert e.value.code == "invalid_param" and "整数" in e.value.extra["message_zh"]


def test_session_rejects_before_sending():
    s = Session()                                     # 没连板子：非法值先被拒（invalid_param），合法值才走到 not_connected
    sent = []
    s._send = lambda *a, **k: sent.append(a) or False
    for bad in ("abc", None, "nan"):
        with pytest.raises(LinkError) as e:
            s.set_param("kp", bad)
        assert e.value.code == "invalid_param"
    assert not sent
