"""#145：confirm_roles 在仿真 car_2wd 上——① 不直接写任何文件，先回 diff；② 确认后只写 $DZBENCH_HOME/projects 副本，
仓库树（apps/、examples/）一字节不变；③ 带 protect 的参数（max_rps: 限幅）不能给 P/I/D/FF；④ Agent 工具拿不到写入权。"""
import hashlib
import pathlib
import subprocess
import time

import pytest

from dzbench.agent import service as S
from dzbench.agent.gateway import GatewayError
from dzbench.session import Session

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _tree_digest():
    h = hashlib.sha256()
    for top in ("apps", "examples"):
        for f in sorted((ROOT / top).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                h.update(f.relative_to(ROOT).as_posix().encode()); h.update(f.read_bytes())
    st = subprocess.run(["git", "status", "--porcelain", "--", "apps", "examples"], cwd=ROOT, capture_output=True, text=True).stdout
    return h.hexdigest(), st


@pytest.fixture
def svc(home):
    s = Session()
    s.connect("sim:car_2wd")
    t0 = time.monotonic()
    while not s.schema and time.monotonic() - t0 < 20:
        time.sleep(0.05)
    o = S.AgentService.__new__(S.AgentService)
    o.s = s
    yield o
    s.disconnect()


@pytest.mark.needs_sim
def test_repo_tree_unchanged_and_writes_only_project_copy(svc, home):
    before = _tree_digest()
    r = svc.confirm_roles({"kp": "P", "ki": "D"})
    assert r["needs_confirm"] and r["change_id"] and "role: D" in r["diff"]
    assert _tree_digest() == before                                  # 第一步：什么都没写
    assert not (home / "projects").exists()
    w = svc.confirm_roles({}, None, confirmed=True, change_id=r["change_id"])
    assert w["written"] and pathlib.Path(w["app_yaml"]).resolve() == (home / "projects" / "car_2wd" / "app.yaml").resolve()
    assert "name: ki" in (home / "projects/car_2wd/app.yaml").read_text("utf-8")
    assert ", role: D }" in (home / "projects/car_2wd/app.yaml").read_text("utf-8")
    assert _tree_digest() == before                                  # 确认后：仓库树仍一字节不变
    with pytest.raises(GatewayError) as e:                           # 同一个 change_id 不能用两次
        svc.confirm_roles({}, None, confirmed=True, change_id=r["change_id"])
    assert e.value.code == "no_change"


@pytest.mark.needs_sim
@pytest.mark.parametrize("role", ["P", "I", "D", "FF"])
def test_protect_param_rejected_for_tuning_roles(svc, home, role):
    before = _tree_digest()
    with pytest.raises(GatewayError) as e:
        svc.confirm_roles({"max_rps": role})
    assert e.value.code == "protect_param_role" and "max_rps" in e.value.message and "保护参数" in e.value.message
    assert e.value.extra["reason"] == "protect_param_role" and e.value.extra["message_zh"]
    assert _tree_digest() == before and not (home / "projects").exists()


@pytest.mark.needs_sim
def test_protect_param_may_be_lim(svc, home):
    r = svc.confirm_roles({"max_rps": "LIM"})
    assert r["needs_confirm"] or r.get("unchanged")


@pytest.mark.needs_sim
def test_repo_app_dir_rejected(svc, home):
    with pytest.raises(GatewayError) as e:
        svc.confirm_roles({"kp": "P"}, str(ROOT / "apps" / "car_2wd"))
    assert e.value.code == "not_project_dir"


def test_agent_tool_cannot_confirm(home):
    """Agent 工具层把 confirmed / change_id 丢掉：只能拿 diff，写入只有界面确认卡（op confirm_roles confirmed=true）。"""
    import inspect
    src = inspect.getsource(S.AgentService.__init__)
    assert '"confirm_roles": lambda roles, app_dir=None, **_: self.confirm_roles(roles, app_dir)' in src
