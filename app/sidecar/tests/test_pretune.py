"""调参前问答（缺口 9）：规则解析、显式选择优先、只收紧护栏、经 service 进 Agent 上下文。"""
from dzbench.agent import pretune
from dzbench.agent.guard import TuneGuard


def test_parse_notes():
    p = pretune.parse_notes("超调不超过 5%，不能反转，电机别来回抖")
    assert p["max_overshoot_pct"] == 5.0
    assert any("不能反转" in c for c in p["hard_constraints"])
    assert p["goal"] == "actuator"
    assert pretune.parse_notes("零超调")["max_overshoot_pct"] == 2.0
    assert "max_overshoot_pct" not in pretune.parse_notes("快一点")        # 认不出就不填


def test_explicit_wins_and_defaults():
    pt = pretune.from_answers({"plant": "unstable", "notes": "超调 3%", "max_overshoot_pct": "8"})
    assert pt.max_overshoot_pct == 8.0                  # 显式填的优先于自由文本
    assert pt.effective_goal() == "conservative"        # 不稳定对象默认稳为主
    assert pretune.from_answers({"plant": "nonsense"}).plant == "other"
    assert pretune.from_answers({"max_overshoot_pct": "abc"}).max_overshoot_pct is None


def test_apply_only_tightens():
    g = TuneGuard({}, True, max_step_ratio=0.1)
    out = pretune.from_answers({"max_overshoot_pct": "30", "aggressiveness": "conservative", "goal": "actuator"}).apply(g)
    assert g.good["overshoot_pct"] == 10.0              # 30% 比默认宽，不放宽
    assert g.max_step_ratio == 0.1                      # 已更紧的配置不被放宽到 0.2
    assert g.weights == "actuator" and out
    g2 = TuneGuard({}, True)
    pretune.from_answers({"max_overshoot_pct": "4", "aggressiveness": "conservative"}).apply(g2)
    assert g2.good["overshoot_pct"] == 4.0 and g2.max_step_ratio == 0.2


def test_service_roundtrip():
    class Loop:
        def __init__(self): self.notes = []
        def note(self, t): self.notes.append(t)
    from dzbench.agent.service import AgentService
    class Svc(AgentService):
        sim = True                                      # 跳过真 Session
    svc = Svc.__new__(Svc)
    svc.pretune, svc.guard, svc.loop = None, None, Loop()
    q = svc.pretune_get()
    assert [x["key"] for x in q["questions"]][:2] == ["plant", "actuator"] and q["current"] is None
    r = svc.pretune_set({"plant": "speed", "actuator": "dc_pwm", "notes": "超调不超过 5%，不能反转"})
    assert r["current"]["max_overshoot_pct"] == 5.0 and any("超调" in a for a in r["applied"])
    assert "优先级高于默认" in svc.loop.notes[-1] and "不能反转" in svc.loop.notes[-1]
    assert svc.pretune_set(None)["current"] is None and svc.pretune is None
