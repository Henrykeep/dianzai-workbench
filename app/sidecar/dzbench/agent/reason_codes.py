"""迭代原因码总表（#139，前端用）：单轮无效（round）、开始被拒 / 中止（abort）、停止 / 发散（stop / diverge）。

docs/dev/reason_codes.json 由 tools/gen_reason_codes.py 从这里生成；tests/test_reason_codes.py 校验后端每个原因码都在表里、zh 非空、文件是最新的。
"""
from __future__ import annotations

from .iterate import ACK_ZH, INVALID_ZH, STOPS_OUTPUT

STOP_ZH = {"pass": "连续 2 轮达标", "estop": "急停", "stopped": "人点了停止迭代", "budget_time": "时间预算用完",
           "budget_rounds": "轮数上限用完", "invalid": "连续 3 轮无效", "no_improve": "连续 3 轮没有改进",
           "unstable": "发散（超调过大）", "blocked": "所有方向都被拒绝或限幅挡住",
           "plant_unresponsive": "对象无响应"}
# 停止原因的可能起因（界面列出来让人逐项排查）
CAUSES_ZH = {"plant_unresponsive": ["没上电", "接线", "方向（执行器 / 传感器极性接反）", "执行器饱和"]}
DIVERGE = {"unstable"}

# 连接阻塞（不是迭代原因码，但界面 / Agent 用同一张表取中文）：kind = blocker
BLOCKER_ZH = {"schema_conflict": "同一哈希对应多份内容不同的数据格式文件，已停止显示和写参数；修复动作按种类：clear_schema_cache（有缓存拷贝，确认后只删这个哈希的缓存并重新识别）/ build（编译产物互冲，重新编译）/ reflash（编译产物与板上固件不符，重新烧录）",
              "fw_estop_unsafe": "此固件存在急停可被误清除的问题，请重新烧录",
              "estop_latched_ident_deferred": "急停中，暂不识别板子",
              "resuming": "正在恢复连接",
              "resume_no_response": "重连后板子没有回应，请按『重新连接』",
              # #164：侧车重启自动连回失败的原因（link.state reason / board=disconnected 的 down_reason）
              "port_not_found": "本地服务重启后没能自动连回上次的板子（口不在了，也没在别的口找到它）",
              "port_ambiguous": "本地服务重启后找到不止一块像原来那块的板子，没有自动连回，请在端口列表里选一下再点“连接”"}

# #164：每个连接 / 恢复原因码都带 message_zh（界面原样显示）；有修复动作的再带 fix_action（前端按它显示按钮）
BLOCKER_FIX = {"resume_no_response": "reconnect", "estop_latched_ident_deferred": "estop_clear", "fw_estop_unsafe": "reflash",
               "port_not_found": "connect", "port_ambiguous": "connect"}

# #164：侧车其它回包 / 事件里的原因码（拒绝、急停回包、阻塞、迭代异常等）：kind = other；界面同样只从这张表取中文
OTHER_ZH = {"clear_schema_cache": "已清除这个哈希的缓存数据格式，正在重新识别板子",
            "commit_declined": "提交没有在确认卡上批准，未执行",
            "commit_failed": "提交失败，未写入仓库",
            "confirm_required": "这一步需要你在界面上确认后才会执行",
            "data_file_missing": "安装包里的数据文件缺失或损坏，请重新安装",
            "error": "后台出错，迭代已停止",
            "fw_too_old": "固件版本太旧，读不到板子身份号，请升级固件后重新烧录",
            "hold": "这块板子的目标不会保持，重新开始实验即可",
            "manual": "人工按下急停",
            "max_step": "设定值一次跳得超过单次最大阶跃，请分几步改",
            "no_board": "没连板子：急停没有送达任何板子",
            "protect_param_role": "保护参数不能当调参角色",
            "range": "参数超出允许范围，被拒绝",
            "replay": "回放中：急停没有送达任何板子",
            "roles_unconfirmed": "有参数没声明作用，需要先确认参数角色",
            "running": "迭代还没结束",
            "state": "急停中，不下发目标",
            "step": "这一步改动太大，被拒绝",
            "step_too_large": "题面幅度超过声明的单步上限",
            "user_action": "你已手动操作连接，自动连回已取消"}
OTHER_FIX = {"commit_declined": "ask_user_commit", "commit_failed": "ask_user_commit", "data_file_missing": "reinstall",
             "fw_too_old": "reflash", "hold": "restart_experiment", "max_step": "lower_step", "protect_param_role": "confirm_roles",
             "roles_unconfirmed": "confirm_roles", "state": "estop_clear"}


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
        if k in STOPS_OUTPUT:
            out[k]["stops_output"] = True
    for k, zh in BLOCKER_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "blocker"})
        out[k]["message_zh"] = zh
        if k in BLOCKER_FIX:
            out[k]["fix_action"] = BLOCKER_FIX[k]
    for k, zh in OTHER_ZH.items():
        out.setdefault(k, {"zh": zh, "kind": "other"})
        out[k].setdefault("message_zh", zh)
        if k in OTHER_FIX:
            out[k].setdefault("fix_action", OTHER_FIX[k])
    for v in out.values():          # #164：每条都有 message_zh（界面原样显示；与 zh 同源）
        v.setdefault("message_zh", v["zh"])
    return dict(sorted(out.items()))
