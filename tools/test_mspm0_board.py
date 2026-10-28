"""MSPM0 板卡校验：QEI/坑脚/复用/冲突（需 third_party/mspm0-sdk）。python3 tools/test_mspm0_board.py"""
import copy, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from boardlib import Report, load_board, mspm0_check
from families import mspm0 as M

B = load_board(pathlib.Path(__file__).parents[1] / "boards/mspm0g3507-tianmengxing/board.yaml")


def run(mut):
    b = copy.deepcopy(B); mut(b["resources"]); r = Report(); mspm0_check(b, r); return r


def main():
    if not M.HDR.exists():
        print("跳过：无 mspm0-sdk"); return
    assert not run(lambda r: None).errors
    r = run(lambda r: r["encoder"][0].update(timer="TIMG7"))
    assert any("[QEI]" in e and "TIMG7" in e for e in r.errors), r.errors
    r = run(lambda r: r["pwm"][0].update(timer="TIMG8", channel=0, pin="PA26"))
    assert any("已被 PWM" in e for e in r.errors), r.errors
    r = run(lambda r: r["gpio"][0].update(pin="PA19"))
    assert any("SWDIO" in w for w in r.warnings), r.warnings
    r = run(lambda r: r.setdefault("i2c", []).append({"name": "IMU", "instance": "I2C1", "scl": "PA10", "sda": "PA11"}))
    assert any("[引脚冲突] PA10" in e for e in r.errors), r.errors
    r = run(lambda r: r["pwm"][0].update(pin="PA14"))
    assert any("[复用]" in e for e in r.errors), r.errors
    print("mspm0 板卡校验自测通过")


main()
