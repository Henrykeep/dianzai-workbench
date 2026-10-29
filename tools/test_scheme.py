#!/usr/bin/env python3
"""tools/scheme.py 的测试：器件库自洽、规则禁用、方案核对（禁用件/不提供/串口超限/备选重复）、2026H 实例。"""
import pathlib
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import req  # noqa: E402
import scheme as sel  # noqa: E402  （不叫 select.py：会遮住标准库 select，subprocess 都会坏）

EX = pathlib.Path(__file__).resolve().parent.parent / "examples/2026H_ball"
PARTS = sel.load_catalog()
R = req.load(EX / "requirements.yaml")
S = yaml.safe_load((EX / "scheme.yaml").read_text(encoding="utf-8"))


def test_catalog_consistent():
    assert sel.catalog_problems(PARTS) == []
    kinds = {p["kind"] for p in PARTS.values()}
    assert {"mcu", "coproc", "sensor", "actuator"} <= kinds
    for need in ("stm32f103c8t6", "stm32f407vet6", "mspm0g3507", "jetson_nano", "maixcam2", "k230", "rpi", "rdk_x3"):
        assert need in PARTS, need


def test_constraint_forbids_candidates():
    forb = sel.forbidden(R)
    ok, banned = sel.candidates(PARTS, "sense.line", forb)
    assert [x["id"] for x in ok] == ["ir_gray_array"]
    assert [(x["id"], why) for x, why in banned] == [("camera_line", "R4（sense.line_camera）")]
    ok, banned = sel.candidates(PARTS, "ui.display", forb)
    assert "tft_st7789_24" not in [x["id"] for x in ok] and banned


def test_2026h_scheme_passes():
    err, warn = sel.check_scheme(R, S, PARTS)
    assert err == [], err
    md = sel.render_scheme(R, S, PARTS)
    assert "flowchart LR" in md and "独立，不接主控" in md


def _bad(**over):
    s = yaml.safe_load(yaml.safe_dump(S)); s.update(over)
    return sel.check_scheme(R, s, PARTS)[0]


def test_scheme_errors():
    assert any("R5" in e for e in _bad(picks={**S["picks"], "ui.display": "tft_st7789_24"}))
    assert any("不提供" in e for e in _bad(picks={**S["picks"], "sense.line": "encoder_ab"}))
    assert any("同一个件" in e for e in _bad(fallback={"sense.ball_pos": "maixcam2"}))
    # c8t6 只有 3 个串口：MaixCAM2 + QD4310 + IMU 串口 + 调试 = 4 → 不够
    e = _bad(mcu="stm32f103c8t6", picks={**S["picks"], "sense.accel": "imu_uart"})
    assert any("串口不够" in x for x in e), e


def test_options_and_init_scheme():
    md = sel.render_options(R, PARTS)
    assert md.index("`sense.line`") < md.index("`link.video`"), "按牵涉分值降序"
    with tempfile.TemporaryDirectory() as t:
        out = pathlib.Path(t) / "s.yaml"
        assert sel.main([str(EX / "requirements.yaml"), "--init-scheme", str(out)]) == 0
        d = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert d["picks"]["sense.line"] == "ir_gray_array" and set(d["picks"]) == set(sel.needs_of(R))


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("✓", k)
    print(f"test_scheme: {n} 项通过")
