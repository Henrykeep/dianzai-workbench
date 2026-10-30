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
    assert r["name"] == "pf-test-board" and _snap(REPO / "boards") == before
    assert subprocess.run(["git", "status", "--porcelain", "boards"], cwd=REPO, capture_output=True, text=True).stdout == ""


def test_board_name_strips_copy_noise_and_finds_uvprojx(tmp_path):
    d = tmp_path / "Bldc - 副本 (6) - 副本"; (d / "MDK-ARM").mkdir(parents=True)
    (d / "Bldc.ioc").write_text(""); (d / "MDK-ARM" / "Bldc.uvprojx").write_text("")
    assert board_name(d) == "bldc"
    c = tmp_path / "Car_Mode1021"; c.mkdir(); (c / "USART.ioc").write_text("")
    assert board_name(c) == "car-mode1021"
    assert find_uvprojx(d).endswith("MDK-ARM/Bldc.uvprojx")
    e = tmp_path / "副本"; e.mkdir(); (e / "F407_motor.ioc").write_text("")
    assert board_name(e) == "f407-motor" and find_uvprojx(e) == ""


def test_scheme_choices_and_apply_picks():
    from dzbench.projflow import scheme_choices, apply_picks
    req = yaml.safe_load((REPO / "examples/2026H_ball/requirements.yaml").read_text(encoding="utf-8"))
    ch = scheme_choices(REPO, req, {"picks": {}})
    wd = next(n for n in ch["needs"] if n["need"] == "act.wheel_drive")
    assert wd["options"] and wd["pick"] == wd["options"][0]["id"] and ch["mcus"]
    t = apply_picks("# 头\nmcu: a\npicks:\n  x.y: p1\nreasons:\n  x.y: 待定\n", {"x.y": "p2", "z.w": "p3"}, {"x.y": "便宜"}, "b")
    d = yaml.safe_load(t)
    assert t.startswith("# 头") and d["mcu"] == "b" and d["picks"] == {"x.y": "p2", "z.w": "p3"} and d["reasons"]["x.y"] == "便宜"


def test_gen_drafts_project_yaml_from_catalog(tmp_path):
    f = Flow(REPO, tmp_path / "h"); dest = tmp_path / "t"; dest.mkdir()
    import shutil
    for n in ("requirements.yaml", "scheme.yaml"):
        shutil.copy(REPO / "examples/2026H_ball" / n, dest / n)
    r = f.preview("gen", {"code": "T1", "dest": str(dest)})
    assert r["rc"] == 0, r["out"]
    assert {c["name"] for c in r["draft"]["chosen"]} == {"chassis", "vision", "ball"}
    assert "project.yaml" in r["draft"]["files"] and "project_gen.h" in r["files"]
    assert not (dest / "project.yaml").exists()                 # 预览不写题目目录
    w = f.accept("gen", {"code": "T1", "dest": str(dest)})
    assert (dest / "project.yaml").exists() and (dest / "subsys/chassis/chassis.c").exists() and str(dest / "requirements.yaml") not in w["written"]
    shutil.rmtree(REPO / "build" / "T1", ignore_errors=True)


def test_keil_needs_second_confirm(tmp_path):
    uv = tmp_path / "x.uvprojx"; uv.write_text("<Project/>")
    f = Flow(REPO, tmp_path / "h")
    with pytest.raises(FlowError) as e:
        f.accept("keil", {"code": "T2", "uvprojx": str(uv), "board": "b", "app": "a"})
    assert e.value.code == "need_confirm" and ".bak" in e.value.fix


def test_scratch_allocs_and_writes_ioc(tmp_path):
    """从零新建：选项按方案主控排序、MSPM0 标不可用；预览生成 .ioc 且 ioc_import 反导无错；确认写到 CubeMX 目录。"""
    import shutil
    f = Flow(REPO, tmp_path / "h"); dest = tmp_path / "t"; dest.mkdir()
    for n in ("requirements.yaml", "scheme.yaml"):
        shutil.copy(REPO / "examples/2026H_ball" / n, dest / n)
    m = {"code": "S1", "dest": str(dest)}
    opts = f.preview("scratch", m)["options"]
    assert opts[0]["ok"] and any(not o["ok"] and o["family"] == "mspm0" for o in opts)
    f1 = next(o for o in opts if o["mcu"] == "stm32f103c8t6" and not o["tpl"])      # 装不下的排在装得下的后面，并写明理由
    assert f1["fit"] is False and "装不下" in f1["why"] and opts.index(f1) > opts.index(next(o for o in opts if o.get("fit")))
    with pytest.raises(FlowError):
        f.preview("scratch", m | {"mcu": "mspm0g3507"})
    assert f.preview("scratch", m | {"mcu": "stm32f103c8t6"})["rc"] != 0     # H 题串口超出 F103C8：报“没分到”，不写半截 .ioc
    for mcu in ("stm32f407vet6",):
        cd = tmp_path / "cm" / mcu
        r = f.preview("scratch", m | {"mcu": mcu, "cubemx_dir": str(cd)})
        assert r["rc"] == 0 and "✗" not in r["out"] and "Mcu.UserName=STM32F" in r["files"][f"{r['name']}.ioc"]
        w = f.accept("scratch", m | {"name": r["name"], "cubemx_dir": str(cd)})
        assert (cd / f"{r['name']}.ioc").exists() and (dest / "alloc" / "alloc.md").exists() and w["written"]
        assert f.preview("scratch_ready", m | {"cubemx_dir": str(cd)})["ready"] is True    # 合成 Core 已写，直接可导入编译
        assert "合成" in (cd / "Core/Src/main.c").read_text(encoding="utf-8")
