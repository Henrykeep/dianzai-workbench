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


F1 = ROOT / "boards" / "stm32f103c8t6-car-cubemx" / "board.yaml"
CAR_F1 = {"mcu": "stm32f103c8t6", "picks": {"sense.line": "ir_gray_array", "wheel_speed": "encoder_ab", "wheel_drive": "dc_motor_hbridge",
                                          "ui.key": "key_gpio", "ui.display": "oled_ssd1306", "vision": "maixcam2"}}


def _pins(b):
    return [r.get(k) for rs in b["resources"].values() for r in rs for k in ("pin", "pin_a", "pin_b", "tx", "rx", "scl", "sda") if r.get(k)]


def test_f1_car_valid_lqfp48():
    b, notes, ex, rep = run(CAR_F1)
    assert not rep.errors and not notes, (rep.errors, notes)
    ps = _pins(b)
    assert len(ps) == len(set(ps)) and not {"PA13", "PA14", "PD0", "PD1"} & set(ps)
    assert all(boardlib_ok(p) for p in ps), ps
    assert {r["timer"] for r in b["resources"]["encoder"]}.isdisjoint({r["timer"] for r in b["resources"]["pwm"]})
    md = alloc.cubemx_md(b, ex, False)
    # TIM1 在 APB2 72 MHz；20 kHz：72e6/20e3 − 1 = 3599（与用户真实 .ioc 的 Period=3600-1 相同）
    assert "Prescaler=0，Counter Period=3599" in md and "72 MHz" in md, md


def boardlib_ok(p):
    from families import stm32f1
    return bool(stm32f1.PIN_RE.match(p))


def test_f1_fixed_real_board_kept():
    fx = boardlib.load_board(F1)
    s = {**CAR_F1, "names": {"ir_gray_array": {"gpio": ["L1", "L2", "L3", "L4", "R1", "R2", "R3", "R4"]}}}   # 真实板的逻辑名
    b, notes, ex, rep = run(s, fx)
    assert not rep.errors, rep.errors
    # 真实小车板：USART1/2 已用作 LINK/AUX，PB10/11 被当 GPIO 占了 → 视觉串口没有了；I2C1/2 的脚都被占（OLED 是软件 I2C GPIO）。必须如实报出
    assert sorted(n.split("：")[0] for n in notes) == ["i2c.OLED", "uart.VISION"], notes
    real = {(t, r["name"]): r for t, rs in fx["resources"].items() for r in rs}
    kept = [(t, r["name"]) for t, rs in b["resources"].items() for r in rs if (t, r["name"]) in real]
    assert ("encoder", "MOTOR_A") in kept and all(r == real[(t, r["name"])] for t, rs in b["resources"].items() for r in rs if (t, r["name"]) in real)
    used = set(_pins(fx))
    new = [p for (t, rs) in b["resources"].items() for r in rs if (t, r["name"]) not in real for p in _pins({"resources": {t: [r]}})]
    assert not used & set(new), used & set(new)      # 新分配的不碰已焊死的脚


def test_f1_remap_groups_enforced():
    bad = {"schema_version": 1, "name": "f1-bad", "port": "stm32-cubemx", "config_source": {"tool": "cubemx", "file": "TODO"},
           "mcu": {"family": "stm32f1", "part": "STM32F103C8T6"},
           "resources": {"pwm": [{"name": "A", "timer": "TIM2", "channel": 1, "pin": "PA0", "freq_hz": 20000},
                                 {"name": "B", "timer": "TIM2", "channel": 2, "pin": "PB3", "freq_hz": 20000}],   # 默认组 + 重映射组混用
                         "uart": [{"name": "LINK", "instance": "USART1", "tx": "PA9", "rx": "PB7", "baud": 115200}],
                         "gpio": [{"name": "X", "pin": "PC6", "dir": "out"}]}}                                  # 48 脚没有 PC6
    rep = boardlib.check_board(bad)
    msg = " ".join(rep.errors)
    assert "[重映射] TIM2" in msg and "[重映射] uart.LINK" in msg and "LQFP48" in msg, rep.errors


def test_f1_exhaustion_four_timers():
    s = {"mcu": "stm32f103c8t6", "picks": {"x": "encoder_ab"}, "names": {"encoder_ab": {"encoder": [f"E{i}" for i in range(5)]}},
         "debug_link_uart": False}
    b, notes, ex, rep = run(s)
    assert sum(1 for r in b["resources"]["encoder"] if r["timer"] != "TODO") == 4 and any("没分到" in n for n in notes)


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


def test_app_timer_requires_allocated_and_names_override():
    """2026X_follow：app.yaml requires timer.CTRL（器件库给不出）由 app_demands 补成需求、分到空闲定时器；
    scheme.yaml names 把灰度 SENSOR1..8 改成应用的 LINE0..7。结果直接满足 app requires。"""
    ex = ROOT / "examples" / "2026X_follow"
    s = yaml.safe_load((ex / "scheme.yaml").read_text(encoding="utf-8"))
    app = yaml.safe_load((ex / "app.yaml").read_text(encoding="utf-8"))
    b, notes, ex_, = alloc.allocate(s, P, None, "t-draft", app)
    rep = boardlib.check_board(b)
    boardlib.check_requires(b, app, rep)
    assert not rep.errors and not notes, (rep.errors, notes)
    tims = {r["instance"] for r in b["resources"]["timer"]}
    used = {r["timer"] for t in ("pwm", "encoder") for r in b["resources"][t]}
    assert tims and not tims & used, (tims, used)
