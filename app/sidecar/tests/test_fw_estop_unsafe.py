"""fw_estop_unsafe：急停可被误清除的固件（dzctl < MIN_ESTOP_SAFE_DZCTL）或没有 'I' 回包 → 驱动执行器的操作全拒，读/存 flash 不拦。"""
import struct

import pytest

from dzbench import board_ident
from dzbench.session import LinkError, Session

ACTUATE = [("send_data", (1, b"\0")), ("set_run_mode", ("standalone", True)), ("run_selftest", ()), ("relay", (0, 1.0, 0.1, 1.0)),
           ("step_start", (0, 1, 1.0, 500)), ("setpoint_set", ("sp", 1.0)), ("set_param", ("kp", 1.0)), ("send_raw", (b"x",))]


def _info(ver: int = 1, proto: int | None = None):
    p = b"I" + struct.pack("<BIIBIII", ver, 0x1234, 500, 1, 1, 2, 0xABCDEF0)
    return board_ident.decode_info(p + (struct.pack("<I", proto) if proto is not None else b""))


def test_constant_and_decode():
    assert board_ident.MIN_ESTOP_SAFE_PROTO == 0x00001200
    v1 = _info(1)
    assert v1["proto_ver"] is None and board_ident.estop_safety(v1)["safe"] is False          # info_ver 1（23 B）：不安全
    v2 = _info(2, 0x00001200)
    assert v2["proto_ver"] == 0x1200 and v2["fw_rev"] == 0xABCDEF0
    assert board_ident.estop_safety(v2)["safe"] is True and board_ident.estop_safety(v2)["version"] == "0.18.0"
    assert board_ident.estop_safety(_info(2, 0x00001109))["safe"] is False                     # 0.17.9
    st = board_ident.estop_safety(None)                                                         # 2 s 没回包
    assert st["reason"] == "fw_estop_unsafe" and st["fix_action"] == "reflash" and st["min_version"] == "0.18.0"
    assert board_ident.estop_safety({"fw_too_old": True})["safe"] is False
    assert board_ident.ESTOP_UNSAFE_ZH == "此固件存在急停可被误清除的问题，请重新烧录"


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setattr(board_ident, "ENFORCE_FW_ESTOP", True)     # 拦截逻辑本身照测（开关只为等 0.18.0 仿真固件进 integration）


def _sess(tmp_path, info, port="COM9"):
    s = Session(log_dir=tmp_path) if "log_dir" in Session.__init__.__code__.co_varnames else Session()
    s.port, s.hb_status = port, 0
    s._set_estop_safety(info)
    return s


@pytest.mark.parametrize("op,args", ACTUATE)
@pytest.mark.parametrize("info", [None, "v1"])
def test_actuators_blocked(tmp_path, op, args, info):
    s = _sess(tmp_path, None if info is None else _info(1))
    with pytest.raises(LinkError) as e:
        getattr(s, op)(*args)
    d = e.value.as_dict()
    assert d["code"] == "fw_estop_unsafe" and d["fix_action"] == "reflash"
    assert d["message_zh"] == board_ident.ESTOP_UNSAFE_ZH and d["min_version"] == "0.18.0"


@pytest.mark.parametrize("op,args", ACTUATE)
def test_safe_fw_and_sim_not_blocked_by_this_guard(tmp_path, op, args):
    for s in (_sess(tmp_path, _info(2, 0x1200)), _sess(tmp_path, None, port="sim:car_2wd")):
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


def test_status_board_ident_only_from_handshake(tmp_path):
    """status 的 board_uid / uid_supported / proto_ver 只转发解码后的 'I' 回包，不由心跳算；带 board_ident_source='handshake'。"""
    s = _sess(tmp_path, None)
    s.board_uid = 0xDEADBEEF                     # 心跳芯片 ID：不得出现在 status
    st = s.status()
    assert st["board_ident_source"] == "handshake" and st["board_uid"] is None and st["proto_ver"] is None
    info = _info(2, 0x1200)
    s._on_info(info)
    st = s.status()
    assert st["board_uid"] == f"{info['board_uid']:016x}" and st["uid_supported"] is True and st["proto_ver"] == 0x1200
    assert "deadbeef" not in str(st.get("board_uid"))


@pytest.mark.xfail(strict=True, reason="pending fw-unknown-cmd 854b6a1 merge; flip ENFORCE_FW_ESTOP to True and host-sim to dzctl 0.18")
def test_enforce_fw_estop_is_on():
    import importlib
    bi = importlib.reload(board_ident)          # 读模块里的真值，不受本文件 autouse 打开开关的影响
    assert bi.ENFORCE_FW_ESTOP is True
