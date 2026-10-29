#!/usr/bin/env python3
"""tools/alloc.py 的测试：分配结果必须过 boardlib（与 validate_board 同一检查）。"""
import pathlib
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import alloc  # noqa: E402
import boardlib  # noqa: E402
import scheme as sch  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
EX = ROOT / "examples" / "2026H_ball"
BLDC = ROOT / "boards" / "stm32f407-bldc-freertos-cubemx" / "board.yaml"
P = sch.load_catalog()


def run(s, fixed=None):
    b, notes, ex = alloc.allocate(s, P, fixed, "t-draft")
    return b, notes, ex, boardlib.check_board(b)


def test_2026h_valid_and_meets_app():
    s = yaml.safe_load((EX / "scheme.yaml").read_text(encoding="utf-8"))
    b, notes, ex, rep = run(s)
    boardlib.check_requires(b, yaml.safe_load((EX / "app.yaml").read_text(encoding="utf-8")), rep)
    assert not rep.errors and not notes, (rep.errors, notes)
    pins = [r.get(k) for rs in b["resources"].values() for r in rs for k in ("pin", "pin_a", "pin_b", "tx", "rx", "scl", "sda")]
    pins = [p for p in pins if p]
    assert len(pins) == len(set(pins)) and "PA13" not in pins and "PA14" not in pins
    assert {r["timer"] for r in b["resources"]["encoder"]}.isdisjoint({r["timer"] for r in b["resources"]["pwm"]})


def test_fixed_board_pins_kept():
    s = yaml.safe_load((EX / "scheme.yaml").read_text(encoding="utf-8"))
    fx = boardlib.load_board(BLDC)
    b, _, ex, rep = run(s, fx)
    assert not rep.errors, rep.errors
    real = {(t, r["name"]): r for t, rs in fx["resources"].items() for r in rs}
    for t, rs in b["resources"].items():
        for r in rs:
            if (t, r["name"]) in real:
                assert r == real[(t, r["name"])]


def test_exhaustion_reported_not_hidden():
    s = {"mcu": "stm32f407vet6", "picks": {f"x{i}": "encoder_ab" for i in range(1)}, "names": {"encoder_ab": {"encoder": [f"E{i}" for i in range(8)]}}}
    b, notes, ex, rep = run(s)
    assert any("没分到" in n for n in notes)
    assert sum(1 for r in b["resources"]["encoder"] if r["timer"] != "TODO") == 6     # F407 能做编码器的：TIM1/2/3/4/5/8


def test_psc_arr_hand_computed():
    s = {"mcu": "stm32f407vet6", "picks": {"servo": "servo_pwm"}, "debug_link_uart": False}
    b, _, ex, rep = run(s)
    md = alloc.cubemx_md(b, ex, False)
    # TIM1 在 APB2，168 MHz；50 Hz：168e6/(PSC+1)/50-1 ≤ 65535 → PSC=51，ARR=168e6//52//50-1=64614
    assert b["resources"]["pwm"][0]["timer"] == "TIM1" and "Prescaler=51，Counter Period=64614" in md, md


def test_family_without_tables_is_honest():
    s = {"mcu": "mspm0g3507", "picks": {"wheel_drive": "dc_motor_hbridge"}}
    b, notes, ex, rep = run(s)
    assert not rep.errors and any("没有复用知识表" in n for n in notes)
    assert all(r.get("pin") == "TODO" for r in b["resources"]["pwm"])
    with tempfile.TemporaryDirectory() as d:
        assert alloc.main([str(EX / "scheme.yaml"), "-o", d, "--app", str(EX / "app.yaml")]) == 0
        assert (pathlib.Path(d) / "cubemx.md").exists()


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1
    print(f"test_alloc: {n} 项通过")
