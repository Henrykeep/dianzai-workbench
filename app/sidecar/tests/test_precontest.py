"""赛前全绿检查：板子状态判定 + 封箱清单导出（host-sim）。"""
import pathlib
import time

import pytest

from dzbench import precontest

ROOT = str(pathlib.Path(__file__).resolve().parents[3])


def by_id(r):
    return {i["id"]: i for i in r["items"]}


def test_not_connected_fails():
    from dzbench.session import Session
    r = precontest.run(Session(), None, [{"id": "x", "name": "x", "level": "ok", "msg": "", "fix": ""}])
    assert not r["all_green"] and by_id(r)["board"]["level"] == "fail" and by_id(r)["x"]["group"] == "电脑"


@pytest.mark.needs_sim
def test_sim_board_checks_and_export(home, tmp_path):
    from dzbench.session import Session
    s = Session()
    s.connect("sim:car_2wd")
    try:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5 and not (s.schema and len(s.params) == 5 and s.status()["alive"]):
            time.sleep(0.05)
        r = precontest.run(s, None, [])
        b = by_id(r)
        assert b["board"]["level"] == "ok" and b["params"]["level"] == "ok" and b["estop"]["level"] == "ok"
        assert b["link"]["level"] == "warn"                       # 刚连上，不满 10 秒数据
        s.set_param("kp", 0.3)
        b = by_id(precontest.run(s, None, []))
        assert b["params"]["level"] == "fail" and "kp" in b["params"]["msg"]   # 调了没定稿：复位就丢
        s.estop()
        r = precontest.run(s, None, [])
        assert by_id(r)["estop"]["level"] == "fail" and not r["all_green"]
        p = pathlib.Path(precontest.export(r, s, None, tmp_path))
        t = p.read_text(encoding="utf-8")
        assert p.parent.name == "seal" and "# 封箱清单" in t and "未全绿" in t and "| kp | 0.3 |" in t and "- [ ] " in t
    finally:
        s.disconnect()


def test_repo_items_dirty(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert precontest.repo_items(str(tmp_path))[0]["level"] == "fail"
