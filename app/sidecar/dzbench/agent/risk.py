"""Agent 工具风险分级（思路参考 embeddedskills，MIT；分级表为本项目自定）。

auto   只读，直接执行
log    自动执行并写审计日志（编译、复位、提议改参数/改文件——提议本身还要人确认才落地）
human  必须人在界面上点“执行”（烧录、擦除、写内存、实机阶跃实验、实机回滚到最好参数）
forbid 永远不给（原始命令、关急停、解 RDP、急停本身）
"""
from __future__ import annotations

import json
import time

from .. import snapshots

AUTO, LOG, HUMAN, FORBID = "auto", "log", "human", "forbid"

RISK: dict[str, str] = {
    "read_telemetry": AUTO, "list_params": AUTO, "step_analysis": AUTO, "list_files": AUTO, "read_file": AUTO,
    "tune_context": AUTO, "read_symbol": AUTO, "decode_hardfault": AUTO, "build_log": AUTO,
    "build": LOG, "reset": LOG, "propose_param_change": LOG, "propose_edit": LOG, "observe": LOG,
    "flash": HUMAN, "erase": HUMAN, "mem_write": HUMAN, "run_step_test": HUMAN, "rollback_best": HUMAN,
    "open_loop_test": HUMAN,                       # 另需 step_test.plant_stable=true（experiment.require_open_loop）
    "swarm_search": FORBID,                        # 群体/随机搜索：实机永远不给，仿真降为 log
    "raw_cmd": FORBID, "disable_estop": FORBID, "unlock_rdp": FORBID, "estop": FORBID,
}
# 仿真里不动真东西：这几项降为 log
SIM_RELAX = {"run_step_test": LOG, "rollback_best": LOG, "swarm_search": LOG}


def tier(tool: str, sim: bool) -> str:
    t = RISK.get(tool, FORBID)                    # 没登记的工具一律禁止（默认拒绝）
    return SIM_RELAX.get(tool, t) if sim else t


def audit(tool: str, args: dict, tier_: str, result: str) -> None:
    p = snapshots.base_dir() / "agent_audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": tool, "tier": tier_,
                            "args": args, "result": result}, ensure_ascii=False, default=str) + "\n")
