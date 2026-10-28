"""分层配置：内置默认 < 本机（~/.dzbench/machine.json）< 工程（<仓库>/dzbench.json）< 环境变量。

思路参考 embeddedskills（MIT）的“工程配置 + 机器配置”分层：工程文件进 git、团队共享（芯片、ELF、阶跃实验、调参门限）；
本机文件放每台电脑不同的东西（Keil UV4 路径、pyOCD、探针序列号）。密钥只能在本机 config.json（llm.py），
工程文件里出现 api_key / password 之类直接报错，防止误提交。
"""
from __future__ import annotations

import copy
import json
import os
import pathlib

from . import snapshots

DEFAULTS: dict = {
    "flash": {"tool": "pyocd", "target": None, "probe": None, "dry_run": True, "keep_previous": True,
              "heartbeat_timeout_s": 3.0},
    "build": {"keil_uv4": None, "keil_project": None, "keil_target": None, "elf": None},
    "tune": {"vbat_min": None, "temp_max": None, "max_rounds_hw": 8, "max_rounds_sim": 20},
    "step_test": None,      # {"kind":"data","id":1,"fmt":"<ff","low":[0,0],"high":[0.4,0],"hold_s":1.5,"y":"spd_a","sp":"sp_a"}
    "core": None,           # "cm0plus" / "cm3" / "cm4" / "cm7"；不填按 flash.target 猜
}
ENV = {"DZBENCH_PYOCD_TARGET": ("flash", "target"), "DZBENCH_PROBE": ("flash", "probe"), "DZBENCH_UV4": ("build", "keil_uv4")}
SECRET_KEYS = ("api_key", "password", "token", "secret")


class ConfigError(Exception):
    pass


def _merge(a: dict, b: dict) -> dict:
    for k, v in b.items():
        a[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a


def _secret(d, path="") -> str | None:
    if isinstance(d, dict):
        for k, v in d.items():
            if any(s in k.lower() for s in SECRET_KEYS):
                return f"{path}{k}"
            r = _secret(v, f"{path}{k}.")
            if r:
                return r
    return None


def _read(p: pathlib.Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{p} 不是合法 JSON：{e}") from e


def load(repo: str | os.PathLike | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    _merge(cfg, _read(snapshots.base_dir() / "machine.json"))
    if repo:
        proj = _read(pathlib.Path(repo) / "dzbench.json")
        bad = _secret(proj)
        if bad:
            raise ConfigError(f"dzbench.json（进 git 的工程配置）里不能放密钥：{bad}；请放到本机 ~/.dzbench/")
        _merge(cfg, proj)
    for env, (a, b) in ENV.items():
        if os.environ.get(env):
            cfg[a][b] = os.environ[env]
    return cfg
