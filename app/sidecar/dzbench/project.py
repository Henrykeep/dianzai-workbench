"""当前项目：侧车记住用户最近创建 / 打开的项目（examples/<题号>/），重启后恢复。

存在 $DZBENCH_HOME/current_project.json（不在仓库里）。项目页引导流程（flow_preview / flow_accept /
project_chain / project_apply）带 code 调用时即视为打开该项目。
读题完成的判据沿用项目流程的约定：项目目录下有 requirements.yaml 且 items 非空（projflow 第 ① 步写出、steptools.project_state 同一判据）。
"""
from __future__ import annotations

import json
import pathlib
import datetime
import re

import yaml

from . import snapshots

_CODE = re.compile(r"^[A-Za-z0-9_\-.]+$")


def _path() -> pathlib.Path:
    return snapshots.base_dir() / "current_project.json"


def set_current(root: pathlib.Path, code: str) -> dict | None:
    if not code or not _CODE.match(code) or code in (".", ".."):
        return None
    d = {"path": str(pathlib.Path(root) / "examples" / code), "name": code}
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
    return d


def current() -> dict | None:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("path") or not d.get("name"):
        return None
    return {"path": d["path"], "name": d["name"]}


def req_items(proj: dict | None) -> int:
    """项目目录下 requirements.yaml 的评分项条数；没有项目 / 文件 / 坏 yaml = 0。"""
    if not proj:
        return 0
    f = pathlib.Path(proj["path"]) / "requirements.yaml"
    try:
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return 0
    items = d.get("items") if isinstance(d, dict) else None
    return len(items) if isinstance(items, list) else 0


class ProjectError(Exception):
    """project.open / project.list 的错误：原因 + 怎么解决 + 修复动作（入口表 id）。"""

    def __init__(self, code: str, msg: str, fix: str, fix_action: str | None = None):
        super().__init__(msg)
        self.code, self.msg, self.fix, self.fix_action = code, msg, fix, fix_action


def _mtime(d: pathlib.Path) -> float:
    m = d.stat().st_mtime
    for f in d.rglob("*"):
        try:
            m = max(m, f.stat().st_mtime)
        except OSError:
            pass
    return m


def list_projects(root: pathlib.Path) -> list[dict]:
    """examples/ 下可打开的项目（只读）：[{code, name, updated_at}]，按最近修改倒序。"""
    ex = pathlib.Path(root) / "examples"
    out = []
    if ex.is_dir():
        for d in ex.iterdir():
            if d.is_dir() and _CODE.match(d.name) and not d.name.startswith("."):
                ts = datetime.datetime.fromtimestamp(_mtime(d)).astimezone().isoformat(timespec="seconds")
                out.append({"code": d.name, "name": d.name, "updated_at": ts})
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return out


def open_project(root: pathlib.Path, code) -> dict:
    """校验题号 → 记为当前项目（持久化）。失败抛 ProjectError。"""
    code = "" if code is None else str(code)
    if not code.strip():
        raise ProjectError("project_code_missing", "未指定要打开的项目代号。",
                           "从项目列表中选择一个项目，或先新建项目。", "project_list")
    if "/" in code or "\\" in code or ".." in code or not _CODE.match(code) or code in (".", ".."):
        raise ProjectError("project_code_invalid", f"项目代号「{code}」不合法：只允许字母、数字、下划线、短横线和点，不能包含路径分隔符或“..”。",
                           "从项目列表中选择已有项目的代号，不要输入路径。", "project_list")
    d = pathlib.Path(root) / "examples" / code
    if not d.is_dir():
        raise ProjectError("project_not_found", f"项目「{code}」不存在：examples/{code}/ 目录未找到。",
                           "从项目列表中选择已有项目，或用“一句话新建工程”创建该项目。", "project_list")
    r = set_current(root, code)
    if r is None:
        raise ProjectError("project_code_invalid", f"项目代号「{code}」不合法。", "从项目列表中选择已有项目。", "project_list")
    return r
