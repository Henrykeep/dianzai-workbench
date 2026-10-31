"""r9g：#115 run_id / manual_step，#121 pass → verdict_zh「通过」，#104 app_dir。"""
import random

from dzbench.agent import service as S
from test_r9e import _svc


def test_iterate_start_new_run_id_reconnect_keeps_it():
    svc, ev = _svc()
    S.AgentService.clear_result(svc, "iterate_start")
    a = ev[-1]["run_id"]
    S.AgentService.clear_result(svc, "reconnect")
    assert ev[-1]["run_id"] == a
    S.AgentService.clear_result(svc, "iterate_start")
    assert ev[-1]["run_id"] != a and ev[-1]["type"] == "result_reset"


def test_pass_verdict_zh_is_tongguo():
    lim = random.Random(5).uniform(1, 5)
    v, zh = S.AgentService._verdict({"inside": True, "band": {"unit": "%", "limit": lim}, "unit": "%"}, {"reason": "pass"})
    assert v == "pass" and zh == "通过"
