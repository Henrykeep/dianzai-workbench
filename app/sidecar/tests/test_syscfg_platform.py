"""SysConfig CLI 按平台找：Windows → sysconfig_cli.bat，POSIX → .sh；找不到 → missing_deps + fetch_deps。"""
import os
import types

import pytest

from dzbench import projflow


def _as_os(monkeypatch, name):
    """只让 projflow 看到的 os.name 变（代理模块）；不动全局 os.name，否则 Windows 上 pathlib 会去实例化 PosixPath。"""
    proxy = types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")})
    proxy.name = name
    monkeypatch.setattr(projflow, "os", proxy)


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    monkeypatch.delenv("SYSCFG_CLI", raising=False)
    monkeypatch.setenv("DZBENCH_REPO", str(tmp_path / "repo"))
    monkeypatch.setattr(projflow.pathlib.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    d = tmp_path / "repo/third_party/sysconfig_1.28.0"
    d.mkdir(parents=True)
    return d


@pytest.mark.parametrize("osname,plat,want", [("nt", "win32", "sysconfig_cli.bat"), ("posix", "linux", "sysconfig_cli.sh"), ("posix", "darwin", "sysconfig_cli.sh")])
def test_picks_platform_script(fake_repo, monkeypatch, osname, plat, want):
    _as_os(monkeypatch, osname)
    monkeypatch.setattr(projflow.sys, "platform", plat)
    (fake_repo / "sysconfig_cli.bat").write_text("@echo off\n")
    (fake_repo / "sysconfig_cli.sh").write_text("#!/bin/sh\n")
    assert projflow.syscfg_cli_name() == want and projflow.syscfg_cli() == fake_repo / want


def test_windows_with_only_sh_is_missing(fake_repo, monkeypatch):
    monkeypatch.setattr(projflow.sys, "platform", "win32")
    (fake_repo / "sysconfig_cli.sh").write_text("#!/bin/sh\n")         # 旧逻辑只找 .sh：Windows 上“找到了”却跑不起来
    assert projflow.syscfg_cli() is None
    with pytest.raises(projflow.FlowError) as ei:
        projflow.require_syscfg_cli()
    assert ei.value.code == "missing_deps" and ei.value.fix_action == "fetch_deps" and "sysconfig_cli.bat" in ei.value.msg


def test_home_fallback_and_env_override(fake_repo, tmp_path, monkeypatch):
    _as_os(monkeypatch, "posix")
    monkeypatch.setattr(projflow.sys, "platform", "linux")
    h = tmp_path / "home/ti/sysconfig_1.28.0"
    h.mkdir(parents=True)
    (h / "sysconfig_cli.sh").write_text("#!/bin/sh\n")
    assert projflow.syscfg_cli() == h / "sysconfig_cli.sh"
    monkeypatch.setenv("SYSCFG_CLI", str(tmp_path / "nope.bat"))
    assert projflow.syscfg_cli() is None                                 # 指了但不存在：也算缺
    monkeypatch.setenv("SYSCFG_CLI", str(h / "sysconfig_cli.sh"))
    assert projflow.require_syscfg_cli() == h / "sysconfig_cli.sh"
