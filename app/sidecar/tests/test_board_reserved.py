"""board.yaml reserved_pins：板级保留脚被占用时 check 报错/告警，允许的用途放行。"""
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import boardlib  # noqa: E402


def _check(res, reserved):
    rep = boardlib.Report()
    boardlib.generic_check({"resources": res, "reserved_pins": reserved}, rep)
    return rep


R = {"PA19": {"reason": "SWDIO"}, "PA10": {"reason": "CH340", "allow": ["uart.LINK."]},
     "PA5": {"reason": "HFXIN", "level": "warn"}}


def test_swd_reuse_is_error():
    rep = _check({"gpio": [{"name": "LED", "pin": "PA19"}]}, R)
    assert any("保留引脚" in e and "PA19" in e for e in rep.errors)


def test_allowed_use_passes():
    rep = _check({"uart": [{"name": "LINK", "tx": "PA10", "rx": "PA11"}]}, R)
    assert not [e for e in rep.errors if "保留引脚" in e]


def test_other_uart_on_ch340_pin_is_error():
    rep = _check({"uart": [{"name": "IMU", "tx": "PA10", "rx": "PA9"}]}, R)
    assert any("PA10" in e for e in rep.errors)


def test_crystal_pin_only_warns():
    rep = _check({"gpio": [{"name": "K", "pin": "PA5"}]}, R)
    assert not rep.errors and any("PA5" in w for w in rep.warnings)
