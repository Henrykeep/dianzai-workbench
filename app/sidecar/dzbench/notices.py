"""阻塞项主动提醒（缺口 #25）：progress 出现新的阻塞项时，以 Agent 身份推一条 agent_notice。

确定性模板，不调用大模型（<1 s）；同一阻塞项只提醒一次，清除后再出现才再提醒。
需要人做的动作（estop_clear / set_run_mode）标 human_only：Agent 只给跳转，不自动执行。
"""
from __future__ import annotations

HUMAN_ONLY = {"estop_clear", "set_run_mode"}

# code → (发生了什么, 建议)
TEMPLATES = {
    "estop": ("急停已锁存，本地服务已停止一切主动发送，自动调参与实验已中止。",
              "请先排除急停原因并确认现场安全，再由操作人员在界面点击“解除急停”。Agent 不会自动解除急停。"),
    "no_board": ("板子已断开或尚未连接，板上状态暂不可信。",
                 "请检查 USB 线与供电后重新连接；重连只恢复通信与遥测，不会重发任何运动指令。"),
    "missing_deps": ("开发环境缺少必需依赖，工程生成与仿真无法继续。",
                     "建议执行“一键安装缺失依赖”后重试。"),
    "gains_zero": ("控制增益全部为零，闭环不会产生输出。",
                   "建议使用“无初值一键起步调参”获得初始增益。"),
    "selftest_fail": ("板上自检未通过，输出保持关闭。",
                      "请按失败项检查接线与传感器，然后重新执行自检。"),
    "params_not_saved": ("板上参数已修改但尚未写入 Flash，断电后将恢复为旧值。",
                         "确认参数无误后执行“保存参数”。"),
}

SOURCE_ZH = {"ui": "界面急停按钮", "agent": "Agent 调用", "heartbeat_lost": "上位机心跳丢失",
             "selftest": "上电自检", "latch_restored": "重连后恢复的急停锁存", "progress": "进度检查", "sidecar": "本地服务"}


def source_zh(src: str | None) -> str:
    if not src:
        return SOURCE_ZH["progress"]
    if src.startswith("firmware:"):
        return "板端固件（" + src.split(":", 1)[1] + "）"
    return SOURCE_ZH.get(src, src)


class Notifier:
    def __init__(self):
        self.active: set[str] = set()

    def update(self, snap: dict) -> list[dict]:
        """传入 progress 快照，返回本次新增阻塞项的 agent_notice 列表（已提醒且未清除的不再提醒）。"""
        bl = snap.get("blockers") or []
        now = {b["code"] for b in bl}
        out = []
        for b in bl:
            c = b["code"]
            if c in self.active:
                continue
            what, sugg = TEMPLATES.get(c, (b.get("message", ""), ""))
            src = b.get("source") or "progress"
            fa = b.get("fix_action")
            detail = b.get("message") or ""
            out.append({"type": "agent_notice", "blocker_code": c, "what": what, "detail": detail,
                        "source": src, "source_zh": source_zh(src), "suggestion": sugg,
                        "fix_action": fa, "human_only": fa in HUMAN_ONLY,
                        "text": f"【{source_zh(src)}】{what}{('（' + detail + '）') if detail else ''}建议：{sugg}"})
        self.active = now
        return out


def cleared_notice() -> dict:
    """人工解除急停后的固定提醒（模板，不调大模型）。"""
    what = "已解除，电机保持静止，需重新开始调参"
    return {"type": "agent_notice", "blocker_code": "estop_cleared", "what": what, "detail": "",
            "source": "ui", "source_zh": source_zh("ui"),
            "suggestion": "确认安全后从“调参”重新开始（解除急停不会自动恢复之前的调参任务）",
            "fix_action": "tune_relay", "human_only": False, "text": what}
