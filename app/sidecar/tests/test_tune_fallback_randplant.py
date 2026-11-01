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
    assert not g["false_pass"], g["errors"]
    assert not g["worse_not_reverted"], g["errors"]
    if res["improvement"] in ("inconclusive", "worse"):
        assert res["unchanged"] and res["default_action"] == "keep_initial"


def test_ss_noise_floor_rejects_unresolvable_ss():
    from dzbench.tuning import autotune as AT
    rng = np.random.default_rng(7)
    y = 1.0 + 0.01 * rng.standard_normal(2000)
    sp = {"ss_err_pct": 0.01}
    assert AT.ss_noise_floor({"ss_err_pct": 0.005}, sp, y, 1.0, 2000)        # 2σ/√N ≈ 0.08% ≫ 0.01%
    assert not AT.ss_noise_floor({"ss_err_pct": 0.005}, {"ss_err_pct": 1.0}, y, 1.0, 2000)
    assert not AT.ss_noise_floor({"ss_err_pct": 0.005}, sp, np.ones(2000), 1.0, 2000)
