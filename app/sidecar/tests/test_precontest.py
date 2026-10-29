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
        while time.monotonic() - t0 < 5 and not (s.schema and len(s.params) == len(s.schema.params) and s.status()["alive"]):
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


def _repo(tmp_path):
    import subprocess
    g = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True).stdout.strip()
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (tmp_path / "firmware").mkdir(); (tmp_path / "firmware" / "a.c").write_text("1", encoding="utf-8")
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "x.md").write_text("1", encoding="utf-8")
    g("add", "-A"); g("commit", "-qm", "1")
    return g, int(g("rev-parse", "--short=7", "HEAD"), 16)


def test_fw_item_relaxed_vs_strict(tmp_path):
    g, rev = _repo(tmp_path)
    r = str(tmp_path)
    assert precontest.fw_item(rev, r)["level"] == "ok"
    assert precontest.fw_item(rev | 0x80000000, r)["level"] == "fail"        # 带改动烧的
    (tmp_path / "docs" / "x.md").write_text("2", encoding="utf-8"); g("commit", "-qam", "doc")
    assert precontest.fw_item(rev, r)["level"] == "ok"                       # 只改文档：默认算一致
    assert precontest.fw_item(rev, r, strict=True)["level"] == "fail"        # 严格：必须是 HEAD
    (tmp_path / "firmware" / "a.c").write_text("3", encoding="utf-8")
    it = precontest.fw_item(rev, r)
    assert it["level"] == "fail" and "firmware/a.c" in it["msg"]             # 未提交的固件改动
    g("commit", "-qam", "fw")
    assert precontest.fw_item(rev, r)["level"] == "fail"                     # 已提交但没重烧
    assert precontest.fw_item(0x0abcdef, r)["level"] == "fail"               # 不在本仓库历史
    assert precontest.fw_item(None, r)["level"] == "warn"


@pytest.mark.needs_sim
def test_sim_blackbox(home):
    from dzbench.session import Session
    s = Session()
    s.connect("sim:car_2wd")
    try:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5 and not s.status()["alive"]:
            time.sleep(0.05)
        recs = s.blackbox()
        assert recs and recs[0]["code"] == 1 and "上电" in recs[0]["text"]
    finally:
        s.disconnect()
