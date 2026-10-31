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
    "read_telemetry": AUTO, "list_params": AUTO, "step_analysis": AUTO, "list_files": AUTO, "read_file": AUTO, "repo_map": AUTO,
    "tune_context": AUTO, "update_plan": AUTO, "board_memory": AUTO, "read_symbol": AUTO, "decode_hardfault": AUTO, "build_log": AUTO, "bode_predict": AUTO,
    "project_state": AUTO, "progress_get": AUTO, "project_list": AUTO, "project_open": AUTO, "score_items": AUTO, "flow_preview": LOG, "project_chain": LOG, "quick_start": LOG, "polarity_check": AUTO, "fft": AUTO, "wave_measure": AUTO, "tune_autopilot": LOG,   # 预览只写 ~/.dzbench/flow 暂存区
    "build": LOG, "reset": LOG, "propose_param_change": LOG, "propose_edit": LOG, "change_status": LOG, "remember": LOG, "observe": LOG,
    "flash": HUMAN, "flash_rollback": HUMAN, "erase": HUMAN, "mem_write": HUMAN, "run_step_test": HUMAN, "run_sweep_test": HUMAN, "rollback_best": HUMAN,
    "flow_accept": HUMAN, "project_apply": HUMAN, "score_run": HUMAN, "score_save": HUMAN, "score_writeback": HUMAN,                          # 写仓库（requirements/scheme/boards/alloc/build、Keil 工程）
    "open_loop_test": HUMAN,
    "iterate_start": HUMAN, "iterate_cancel": AUTO,
    "autotune": HUMAN, "confirm_roles": HUMAN, "project_from_plant": LOG,     # #108 通用整定（连续写参数）/ 把人确认的参数角色写回 app.yaml
    "iterate_apply_best": HUMAN, "project_fork": HUMAN,   # project_fork：以内置例题为模板新建项目（#55，写用户项目目录）                   # #53 迭代结束出的“采用最好参数”卡：仿真也要人点（不进 SIM_RELAX）   # #38：实机一张批量卡；停止随时可以                       # 另需 step_test.plant_stable=true（experiment.require_open_loop）
    "swarm_search": FORBID,                        # 群体/随机搜索：实机永远不给，仿真降为 log
    "raw_cmd": FORBID, "disable_estop": FORBID, "unlock_rdp": FORBID, "estop": FORBID,
}
# 工具中文名（界面工具条 / 确认卡 / 审计都用这一份；每个登记的工具都要有，test_risk_names 守）
NAME_ZH: dict[str, str] = {
    "autotune": "通用自动整定", "board_memory": "板子记忆", "bode_predict": "伯德图预测", "build": "编译", "build_log": "编译日志",
    "change_status": "改状态", "confirm_roles": "确认参数角色", "decode_hardfault": "解析 HardFault", "disable_estop": "关闭急停",
    "erase": "擦除芯片", "estop": "急停", "fft": "频谱分析", "flash": "烧录", "flash_rollback": "回滚固件", "flow_accept": "确认写入一步",
    "flow_preview": "预览一步", "iterate_apply_best": "采用最好参数", "iterate_cancel": "停止迭代", "iterate_start": "自动迭代调参",
    "list_files": "列文件", "list_params": "列参数", "mem_write": "写内存", "observe": "观察", "open_loop_test": "开环测试",
    "polarity_check": "极性检查", "progress_get": "查看进度", "project_apply": "写入项目", "project_chain": "整链预览",
    "project_fork": "以例题为模板新建项目", "project_from_plant": "按被控对象声明新建", "project_list": "项目列表", "project_open": "打开项目",
    "project_state": "项目状态", "propose_edit": "提议改文件", "propose_param_change": "提议改参数", "quick_start": "一句话起项目",
    "raw_cmd": "原始命令", "read_file": "读文件", "read_symbol": "读符号", "read_telemetry": "读遥测", "remember": "记下来",
    "repo_map": "仓库地图", "reset": "复位", "rollback_best": "回到最好参数", "run_step_test": "阶跃实验", "run_sweep_test": "扫频实验",
    "score_items": "评分项", "score_run": "评分实验", "score_save": "保存评分", "score_writeback": "回写评分", "step_analysis": "阶跃分析",
    "swarm_search": "群体搜索", "tune_autopilot": "一键起步调参", "tune_context": "调参上下文", "unlock_rdp": "解除读保护",
    "update_plan": "更新计划", "wave_measure": "波形测量",
}
TIER_ZH = {AUTO: "只读", LOG: "自动执行并记录", HUMAN: "需人确认", FORBID: "禁止"}


def describe(tool: str, sim: bool) -> dict:
    """工具的风险档 + 中文名（agent_tool / agent_action 事件带上）。"""
    t = tier(tool, sim)
    return {"tier": t, "tier_zh": TIER_ZH[t], "name_zh": NAME_ZH.get(tool, tool)}


# 仿真里不动真东西：这几项降为 log
SIM_RELAX = {"iterate_start": LOG, "autotune": LOG, "run_step_test": LOG, "run_sweep_test": LOG, "rollback_best": LOG, "swarm_search": LOG, "score_run": LOG}


def tier(tool: str, sim: bool) -> str:
    t = RISK.get(tool, FORBID)                    # 没登记的工具一律禁止（默认拒绝）
    return SIM_RELAX.get(tool, t) if sim else t


def audit(tool: str, args: dict, tier_: str, result: str) -> None:
    p = snapshots.base_dir() / "agent_audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": tool, "tier": tier_,
                            "args": args, "result": result}, ensure_ascii=False, default=str) + "\n")
