"""迭代原因码总表（#139，前端用）：单轮无效（round）、开始被拒 / 中止（abort）、停止 / 发散（stop / diverge）。

docs/dev/reason_codes.json 由 tools/gen_reason_codes.py 从这里生成；tests/test_reason_codes.py 校验后端每个原因码都在表里、zh 非空、文件是最新的。
"""
from __future__ import annotations

from .iterate import ACK_ZH, INVALID_ZH

STOP_ZH = {"pass": "连续 2 轮达标", "estop": "急停", "stopped": "人点了停止迭代", "budget_time": "时间预算用完",
           "budget_rounds": "轮数上限用完", "invalid": "连续 3 轮无效", "no_improve": "连续 3 轮没有改进",
           "unstable": "发散（超调过大）", "blocked": "所有方向都被拒绝或限幅挡住",
           "plant_unresponsive": "对象无响应"}
# 停止原因的可能起因（界面列出来让人逐项排查）
CAUSES_ZH = {"plant_unresponsive": ["没上电", "接线", "方向（执行器 / 传感器极性接反）", "执行器饱和"]}
CAUSES_ZH["improvement_unconfirmed"] = ["测量噪声大", "采样窗口偏短", "改善幅度小于重复测量的波动"]
CAUSES_ZH["kept_initial"] = ["调后参数在某个终验窗口实测代价高于初值"]
# 整定结果卡（autotune）的结论原因码
TUNE_ZH = {"improvement_unconfirmed": "数据噪声大，无法确认比初值好，建议保留初值或加长采样后重测",
           "kept_initial": "调参未能改善，已保留初值",
           "noise_amplified_saturation": "初值微分过大，噪声被放大，执行器长时间饱和；已减小微分"}
# #164 整定器（autotune）能发出的其余码：停止原因 stop_reason、未达标类别 category，全部进表、都带 message_zh
from ..tuning import autotune as _AT  # noqa: E402

for _k, _zh in {**_AT.STOP_ZH, **_AT.CAUSE_ZH, "unconfirmed": "原因待确认：特征不足以归类",
                "max_rounds": "轮数上限用完",
                "step_too_large": "设定值一次跳得超过工程声明的单次最大阶跃 max_step，已拒绝"}.items():
    TUNE_ZH.setdefault(_k, _zh)
CAUSES_ZH["noise_amplified_saturation"] = ["微分增益过大", "传感器噪声大", "缺少微分滤波"]
DIVERGE = {"unstable"}
# 连接阻塞（不是迭代原因码，但界面 / Agent 用同一张表取中文）：kind = blocker
BLOCKER_ZH = {"schema_conflict": "同一哈希对应多份内容不同的数据格式文件，已停止显示和写参数；修复动作 clear_schema_cache（确认后只删这个哈希的缓存格式文件并重新识别）",
              "fw_estop_unsafe": "此固件存在急停可被误清除的问题，请重新烧录",
              "estop_latched_ident_deferred": "急停中，暂不识别板子",
              "resuming": "正在恢复连接"}

# #164 其余侧车会发出的码（会话 / 网关 / 数据文件 / 迭代拒绝等）：kind = misc；文案与 fix-r9c 共用（同一份）
MISC_ZH = {
    "clear_schema_cache": "已清除这个哈希的缓存数据格式文件，正在重新识别",
    "commit_declined": "提交需要你在确认卡上批准，未执行",
    "commit_failed": "git 提交失败，详见日志",
    "confirm_required": "需要在界面上确认后再执行",
    "data_file_missing": "缺少数据文件",
    "error": "内部错误，迭代已停止",
    "fw_too_old": "固件版本太旧，不支持板子唯一标识，请升级固件",
    "hold": "这块板子的目标不会保持，重新开始实验即可",
    "max_step": "设定值一次跳得超过单次最大阶跃",
    "no_board": "没有连接板子",
    "plant_invalid": "对象声明有误，请修改工程声明",
    "protect_param_role": "参数角色未确认，不能写这些参数",
    "range": "参数超出声明范围，已拒绝",
    "replay": "回放中：急停没有送达任何板子",
    "roles_unconfirmed": "参数角色还没确认",
    "running": "迭代还没结束",
    "state": "急停中不下发目标",
    "step": "单次改参步子太大，已拒绝",
    "user_action": "你手动操作过，不自动恢复",
}


def table() -> dict:
    out = {}
    for k, zh in INVALID_ZH.items():
        out[k] = {"zh": zh, "kind": "round"}
    for k, zh in ACK_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "abort"})
    for k, zh in STOP_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "diverge" if k in DIVERGE else "stop"})
        if k in CAUSES_ZH:
            out[k].update(message_zh=zh, causes=CAUSES_ZH[k])
    for k, zh in TUNE_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "tune", "message_zh": zh})
        if k in CAUSES_ZH:
            out[k]["causes"] = CAUSES_ZH[k]
    for k, zh in BLOCKER_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "blocker"})
    for k, zh in MISC_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "misc", "message_zh": zh})
    return dict(sorted(out.items()))
