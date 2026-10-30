"""协处理器 SSH 部署（缺口 12）：假 ssh/scp 在本机模拟远端，走推脚本 → 启动 → 看日志 → 停。"""
import json
import os
import pathlib
import time

import pytest

from dzbench import deploy, snapshots

FAKE = pathlib.Path(__file__).parent / "fakessh"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="假 ssh 是 POSIX 脚本")


@pytest.fixture
def remote(home, tmp_path, monkeypatch):
    r = tmp_path / "remote"; r.mkdir()
    monkeypatch.setenv("DZBENCH_SSH", str(FAKE / "ssh"))
    monkeypatch.setenv("DZBENCH_SCP", str(FAKE / "scp"))
    monkeypatch.setenv("FAKE_SSH_HOME", str(r))
    monkeypatch.setenv("FAKE_SSH_LOG", str(tmp_path / "ssh.log"))
    return r


def test_config_presets_and_validation(home):
    c = deploy.load()
    assert c["kind"] == "maixcam" and c["user"] == "root" and c["host"] == ""
    c = deploy.save({"kind": "jetson", "host": "192.168.1.20"})
    assert (c["user"], c["dir"]) == ("jetson", "~/dz")                       # 换板子带出该板默认
    m = json.loads((snapshots.base_dir() / "machine.json").read_text())
    assert m["coproc"]["host"] == "192.168.1.20"
    for bad in ({"kind": "esp32"}, {"host": "1.2.3.4; rm -rf /"}, {"user": "a b"}, {"entry": "../x.py"}, {"password": "123"}):
        with pytest.raises(deploy.DeployError):
            deploy.save(bad)
    with pytest.raises(deploy.DeployError) as e:
        deploy.Deployer({**deploy.load(), "host": ""}).status()
    assert e.value.code == "no_host"


def test_push_start_log_stop(remote, tmp_path):
    src = tmp_path / "vision"; src.mkdir()
    (src / "main.py").write_text("import time\nprint('dz vision up', flush=True)\ntime.sleep(30)\n")
    (src / "util.py").write_text("X = 1\n")
    (src / ".git").mkdir()
    cfg = deploy.save({"kind": "rpi", "host": "10.0.0.9", "entry": "main.py"})
    d = deploy.Deployer(cfg)
    r = d.push(str(src))
    assert sorted(r["pushed"]) == ["main.py", "util.py"]                    # 隐藏目录不推
    assert (remote / "dz/main.py").exists() and not (remote / "dz/.git").exists()
    assert d.status() == {"running": False, "pid": None}
    s = d.start()
    assert s["pid"] > 0
    with pytest.raises(deploy.DeployError) as e:
        d.start()
    assert e.value.code == "running"
    for _ in range(50):
        if "dz vision up" in d.log(20)["text"]:
            break
        time.sleep(0.1)
    assert "dz vision up" in d.log(20)["text"]
    assert d.status()["running"] and d.status()["pid"] == s["pid"]
    st = d.stop()
    assert st["stopped"] and not d.status()["running"]
    assert d.stop()["stopped"] is False
    log = (tmp_path / "ssh.log").read_text()
    assert "BatchMode=yes" in log and "pi@10.0.0.9" in log                  # 只走密钥登录


def test_unreachable(remote, monkeypatch):
    monkeypatch.setenv("FAKE_SSH_DOWN", "1")
    d = deploy.Deployer(deploy.save({"host": "10.0.0.9"}))
    with pytest.raises(deploy.DeployError) as e:
        d.status()
    assert e.value.code == "ssh_fail" and "ssh-copy-id" in str(e.value)
