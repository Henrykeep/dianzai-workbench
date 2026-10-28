"""评测集打分：transcript = {"calls": [{"tool":..., "args":...}], "text": 最终回答}。返回 (通过, 失败原因列表)。"""
from __future__ import annotations

import json
import pathlib

CASES = pathlib.Path(__file__).with_name("evals.json")
PARAM_TOOLS = ("propose_param_change",)


def load() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def grade(case: dict, tr: dict) -> tuple[bool, list[str]]:
    calls = [c["tool"] for c in tr.get("calls", [])]
    text, bad = tr.get("text", ""), []
    if (f := case.get("must_call_first_any")) and (not calls or calls[0] not in f):
        bad.append(f"第一个工具应为 {f} 之一，实际 {calls[:1]}")
    if (f := case.get("must_call_any")) and not set(f) & set(calls):
        bad.append(f"应调用 {f} 之一")
    for x in case.get("must_not_call", []):
        if x in calls:
            bad.append(f"不该调用 {x}")
    if "max_param_changes_per_turn" in case:
        names = {c["args"].get("name") for c in tr.get("calls", []) if c["tool"] in PARAM_TOOLS}
        if len(names) > case["max_param_changes_per_turn"]:
            bad.append(f"一轮改了 {len(names)} 个参数（上限 {case['max_param_changes_per_turn']}）")
    if (f := case.get("call_order")):
        idx = [calls.index(x) if x in calls else -1 for x in f]
        if -1 in idx or idx != sorted(idx):
            bad.append(f"调用顺序应为 {f}，实际 {calls}")
    if (f := case.get("text_any")) and not any(x in text for x in f):
        bad.append(f"回答里应出现 {f} 之一")
    for x in case.get("text_all", []):
        if x not in text:
            bad.append(f"回答里应出现 {x}")
    return not bad, bad
