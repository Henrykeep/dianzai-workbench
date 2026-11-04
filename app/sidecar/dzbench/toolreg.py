"""工具箱声明（tools.d/*.yaml，字段见 feedback tool-api-draft v0）：启动时扫描，按依赖算状态。
本批只登记从开源项目接入的工具；其余工具的声明由各负责人补（同一格式）。中文原因只从 reason_codes 表取。"""
from __future__ import annotations

import importlib
import pathlib

import yaml

DIR = pathlib.Path(__file__).resolve().parent / "tools.d"
STAGES = ["读题", "方案", "硬件", "固件", "调试", "调参", "报告"]
REQUIRED = ("id", "stage", "icon", "name_zh", "summary_zh", "run", "status_from", "source")


def load() -> list[dict]:
    out = []
    for f in sorted(DIR.glob("*.yaml")):
        d = yaml.safe_load(f.read_text("utf-8"))
        miss = [k for k in REQUIRED if k not in d]
        if miss or d["stage"] not in STAGES or d["id"] != f.stem:
            raise ValueError(f"{f.name}: 声明不合格 缺 {miss} / 阶段 {d.get('stage')} / id 与文件名不一致")
        out.append(d)
    return out


def tool_list() -> dict:
    from .agent.reason_codes import table
    rc = table()
    tools = []
    for d in load():
        st = importlib.import_module(f".{d['status_from']}", __package__).status(d["id"])
        card = {k: d[k] for k in ("id", "stage", "icon", "name_zh", "summary_zh")}
        card.update(status=st["status"], path="sidecar", advanced=bool(d.get("advanced", False)), last_used=None)
        if st.get("reason_code"):
            card.update(reason_code=st["reason_code"], fix_action=rc.get(st["reason_code"], {}).get("fix_action"))
        tools.append(card)
    return {"stages": STAGES, "tools": tools}


def tool_get(tool_id: str) -> dict | None:
    for d in load():
        if d["id"] == tool_id:
            return {k: v for k, v in d.items() if k != "status_from"}
    return None
