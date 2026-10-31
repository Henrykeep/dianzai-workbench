"""#78 门禁骨架：替身对象可复现、假达标必红、题面指标抽取、固定种子冒烟。随机大批量在 tools/tunegate.py。"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import randplant_standin as RP  # noqa: E402
import tunegate as TG  # noqa: E402

from dzbench.tuning import autotune as AT  # noqa: E402


def test_standin_is_reproducible_and_marked(tmp_path):
    a, b = RP.make(42, "any", str(tmp_path / "a")), RP.make(42, "any", str(tmp_path / "b"))
    assert json.dumps(a["plant"], sort_keys=True) == json.dumps(b["plant"], sort_keys=True)
    p = json.loads((tmp_path / "a" / "plant.json").read_text("utf-8"))
    assert p["standin"] is True and "reference" in p and isinstance(p["feasible"], bool)
    assert {f.name for f in (tmp_path / "a").iterdir()} >= {"app.yaml", "link.yaml", "spec.txt", "plant.json"}


def test_param_names_are_random_not_pid_only(monkeypatch):
    monkeypatch.setattr(RP, "reference", lambda *a, **k: {"metrics": {"ss_err_pct": 0.0, "overshoot_pct": 0.0, "settle_s": 1.0, "iae": 0.0}})
    ps = [d for s in range(40) for d in RP.make(s)["app"]["params"]]
    names, roles = {d["name"] for d in ps}, {d["role"] for d in ps}
    assert len(names) > 8 and roles >= {"kp", "ki", "kd", "ff"}


def test_parse_spec():
    sp = AT.parse_spec("要求：稳态误差不超过 2%，超调量 ≤ 10%，调节时间不超过 3.5 s。")
    assert (sp["ss_err_pct"], sp["overshoot_pct"], sp["settle_s"]) == (2.0, 10.0, 3.5) and not sp["default"]
    assert AT.parse_spec("让它转起来")["note_zh"] == "按默认判定"


INFEASIBLE_SEED = 1001      # 替身里 cause=saturation 的对象（test_infeasible_seed_is_infeasible 守着）


def _infeasible_seed():
    return INFEASIBLE_SEED


def test_infeasible_seed_is_infeasible():
    p = RP.make(INFEASIBLE_SEED)["plant"]
    assert p["feasible"] is False and p["infeasible_reason"] == "saturation"


def test_fake_pass_on_infeasible_is_red(monkeypatch):
    s = _infeasible_seed()
    real = AT.autotune
    monkeypatch.setattr(AT, "autotune", lambda *a, **k: real(*a, **k) | {"verdict": "pass", "category": None})
    r = TG.one(s, "any")
    assert not r["ok"] and any("假达标" in e for e in r["errors"]), r


def test_gate_main_prints_seed_on_failure(monkeypatch, capsys):
    s = _infeasible_seed()
    monkeypatch.setattr(AT, "autotune", lambda *a, **k: {"verdict": "pass", "category": None, "pass_basis": "",
                                                          "initial": {"roles": {}}, "best": {"roles": {"kp": 0.0}}})
    assert TG.main(["--seed", str(s)]) == 1
    assert f"失败 seed：{s}" in capsys.readouterr().out
