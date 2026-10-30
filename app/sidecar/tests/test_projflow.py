"""项目页引导流程：运行只写暂存区，确认才写目标（dzbench/projflow.py）。"""
import pathlib, subprocess, yaml, pytest
from dzbench.projflow import Flow, FlowError, alias_rows, apply_alias_edits, board_name, find_uvprojx

REPO = pathlib.Path(__file__).resolve().parents[3]
PROJ = REPO / "tools/testdata/real/projects/Car_Mode1021"


def _snap(p):
    return sorted(str(x.relative_to(p)) for x in p.rglob("*")) if p.exists() else []


def test_alias_edit_keeps_comments():
    t = "pins:\n  PA0: MOTOR_L_PWM   # 原标签 TIM2_CH1\n  PB1: LED  # LED\n"
    rows = alias_rows(t)
    assert rows[0]["key"] == "PA0" and rows[0]["alias"] == "MOTOR_L_PWM" and "TIM2_CH1" in rows[0]["note"]
    out = apply_alias_edits(t, {"PA0": "pwm_left"})
    assert "PWM_LEFT" in out and "原标签 TIM2_CH1" in out and "PB1: LED" in out


def test_req_scheme_alloc_preview_then_accept(tmp_path):
    f = Flow(REPO, home=tmp_path / "home"); dest = tmp_path / "ex"
    src = tmp_path / "t.txt"; src.write_text("一、任务\n设计一个小车。\n二、要求\n1．基本要求\n(1) 小车 10 s 内行驶 2 m。（20 分）\n", encoding="utf-8")
    m = {"code": "T1", "dest": str(dest)}
    r = f.preview("req", m | {"src": str(src)})
    assert r["rc"] == 0 and r["items"] and not dest.exists()        # 没确认：目标不存在
    items = r["items"]; items[0]["text"] = "改过的原文"
    f.accept("req", m | {"items": items})
    assert yaml.safe_load((dest / "requirements.yaml").read_text(encoding="utf-8"))["items"][0]["text"] == "改过的原文"
    r = f.preview("scheme", m)
    assert "scheme.yaml" in r["files"] and not (dest / "scheme.yaml").exists()
    f.accept("scheme", m)
    assert (dest / "scheme.yaml").exists()
    with pytest.raises(FlowError):
        Flow(REPO, home=tmp_path / "h2").preview("alloc", {"code": "T2", "dest": str(tmp_path / "none")})


@pytest.mark.skipif(not PROJ.exists(), reason="no real project fixture")
def test_import_preview_does_not_touch_boards(tmp_path):
    before = _snap(REPO / "boards")
    r = Flow(REPO, home=tmp_path).preview("import", {"code": "T", "project": str(PROJ), "name": "pf_test_board"})
    assert r["name"] == "pf_test_board" and _snap(REPO / "boards") == before
    assert subprocess.run(["git", "status", "--porcelain", "boards"], cwd=REPO, capture_output=True, text=True).stdout == ""


def test_board_name_strips_copy_noise_and_finds_uvprojx(tmp_path):
    d = tmp_path / "Bldc - 副本 (6) - 副本"; (d / "MDK-ARM").mkdir(parents=True)
    (d / "Bldc.ioc").write_text(""); (d / "MDK-ARM" / "Bldc.uvprojx").write_text("")
    assert board_name(d) == "bldc"
    assert find_uvprojx(d).endswith("MDK-ARM/Bldc.uvprojx")
    e = tmp_path / "副本"; e.mkdir(); (e / "F407_motor.ioc").write_text("")
    assert board_name(e) == "f407_motor" and find_uvprojx(e) == ""
