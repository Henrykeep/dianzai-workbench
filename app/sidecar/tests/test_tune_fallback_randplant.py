"""随机对象回归：整定器交付的参数要么带噪真值不比初值差、要么已退回初值；卡上 pass 时带噪真值必须满足题面。
真值只在这里（测试）和判卷里读；种子由固定 rng 抽，不写死任何个案。"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))

SEEDS = [int(s) for s in np.random.default_rng(20261101).integers(28700000, 28800000, size=6)]


@pytest.mark.parametrize("seed", SEEDS)
def test_no_false_pass_and_no_worse_kept(seed, tmp_path):
    import yaml
    import tunegate_grade as G
    import tunegate_plant as RP
    from dzbench.tuning import autotune as AT
    RP.make(seed, "any", str(tmp_path))
    app = yaml.safe_load(open(tmp_path / "app.yaml"))
    link = yaml.safe_load(open(tmp_path / "link.yaml"))
    spec = (tmp_path / "spec.txt").read_text()
    res = AT.autotune(G.board(str(tmp_path), app, seed, "randplant"), app, link, spec, seed)
    g = G.grade(str(tmp_path), seed, res, app, spec, "randplant")
    # 硬门禁：卡上 pass 时真值（无噪 + 带噪 K 均值）必须满足题面；比初值差（成对 t 红）必须已退回
    assert not any(e.startswith("假达标：卡上 pass") for e in g["errors"]), g["errors"]
    assert not g["worse_not_reverted"], g["errors"]
    if res["improvement"] in ("inconclusive", "worse"):
        assert res["unchanged"] and res["default_action"] == "keep_initial"


def test_ss_noise_floor_uses_repeat_spread():
    from dzbench.tuning import autotune as AT
    sp = {"ss_err_pct": 0.01}
    spread = [{"ss_err_pct": x} for x in (0.014, 0.003, 0.006, 0.002)]          # 均值在限内，但散布大 → 测不准
    tight = [{"ss_err_pct": x} for x in (0.003, 0.0031, 0.0029, 0.003)]
    assert AT.ss_noise_floor(spread, sp)
    assert not AT.ss_noise_floor(tight, sp)
    assert not AT.ss_noise_floor(spread, {"ss_err_pct": 1.0})
