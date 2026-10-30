"""当前项目：侧车记住用户最近创建 / 打开的项目（examples/<题号>/），重启后恢复。

存在 $DZBENCH_HOME/current_project.json（不在仓库里）。项目页引导流程（flow_preview / flow_accept /
project_chain / project_apply）带 code 调用时即视为打开该项目。
读题完成的判据沿用项目流程的约定：项目目录下有 requirements.yaml 且 items 非空（projflow 第 ① 步写出、steptools.project_state 同一判据）。
"""
from __future__ import annotations

import json
import pathlib
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
