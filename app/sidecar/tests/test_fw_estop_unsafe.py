"""fw_estop_unsafe：急停可被误清除的固件（dzctl < MIN_ESTOP_SAFE_DZCTL）或没有 'I' 回包 → 驱动执行器的操作全拒，读/存 flash 不拦。"""
import struct

import pytest

from dzbench import board_ident
from dzbench.session import LinkError, Session

ACTUATE = [("send_data", (1, b"\0")), ("set_run_mode", ("standalone", True)), ("run_selftest", ()), ("relay", (0, 1.0, 0.1, 1.0)),
           ("step_start", (0, 1, 1.0, 500)), ("setpoint_set", ("sp", 1.0)), ("set_param", ("kp", 1.0)), ("send_raw", (b"x",))]


def _info(ver=None):
    p = b"I" + struct.pack("<BIIBIII", 2 if ver else 1, 0x1234, 500, 1, 1, 2, 0xABCDEF0)
    return board_ident.decode_info(p + (bytes(ver) if ver else b""))


def test_constant_and_decode():
    assert board_ident.MIN_ESTOP_SAFE_DZCTL == (0, 18, 0)
    assert board_ident.estop_safety(_info())["safe"] is False                 # 0.17 回包：fw_rev 是 git 哈希，读不出版本
    assert board_ident.estop_safety(None)["reason"] == "fw_estop_unsafe"        # 没回包
    assert board_ident.estop_safety({"fw_too_old": True})["fix_action"] == "reflash"
    assert board_ident.estop_safety(_info((0, 17, 9)))["safe"] is False
    assert board_ident.estop_safety(_info((0, 18, 0)))["safe"] is True
    assert board_ident.ESTOP_UNSAFE_ZH == "此固件存在急停可被误清除的问题，请重新烧录"


def _sess(tmp_path, info, port="COM9"):
    s = Session(log_dir=tmp_path) if "log_dir" in Session.__init__.__code__.co_varnames else Session()
    s.port, s.hb_status = port, 0
    s._set_estop_safety(info)
    return s


@pytest.mark.parametrize("op,args", ACTUATE)
@pytest.mark.parametrize("info", [None, "old"])
def test_actuators_blocked(tmp_path, op, args, info):
    s = _sess(tmp_path, None if info is None else _info())
    with pytest.raises(LinkError) as e:
        getattr(s, op)(*args)
    d = e.value.as_dict()
    assert d["code"] == "fw_estop_unsafe" and d["fix_action"] == "reflash"
    assert d["message_zh"] == board_ident.ESTOP_UNSAFE_ZH and d["min_version"] == "0.18.0"


@pytest.mark.parametrize("op,args", ACTUATE)
def test_safe_fw_and_sim_not_blocked_by_this_guard(tmp_path, op, args):
    for s in (_sess(tmp_path, _info((0, 18, 0))), _sess(tmp_path, None, port="sim:car_2wd")):
        try:
            getattr(s, op)(*args)
        except LinkError as e:
            assert e.code != "fw_estop_unsafe"
        except Exception:  # noqa: BLE001  没连板子等其它失败与本守卫无关
            pass


def test_reads_and_save_not_blocked(tmp_path):
    s = _sess(tmp_path, None)
    for fn in (lambda: s.read_param("kp"), lambda: s.save_params(wait_s=0.01), lambda: s.status()):
        try:
            fn()
        except LinkError as e:
            assert e.code != "fw_estop_unsafe"
        except Exception:  # noqa: BLE001
            pass
