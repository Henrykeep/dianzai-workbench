"""Agent 一轮里任何异常 → agent_error 事件（不再静默）；本轮作废，下一句照常能用。"""
import pytest

from dzbench.agent import llm
from dzbench.agent.service import AgentService
from dzbench.agent_api import AgentTools
from dzbench.session import Session
from test_llm_client import serve

KEY = "sk-secret-ABCDEFG123456"
OK = {"choices": [{"message": {"role": "assistant", "content": "收到"}}]}


@pytest.fixture
def svc_srv(tmp_path, monkeypatch):
    for k in ("DZBENCH_API_KEY", "DZ_LLM_API_KEY", "DZ_LLM_BASE_URL", "DZBENCH_BASE_URL", "DZBENCH_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path))
    state = {"code": 200}
    srv, url, _ = serve(lambda h, b: (state["code"], "json", OK if state["code"] == 200 else {"error": {"message": f"blocked {KEY}"}}))
    s, ev = Session(), []
    client = llm.OpenAICompat({"provider": "custom", "base_url": url + "/v1", "model": "m", "api_key": KEY}, retries=0, stream=False)
    svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path, llm=client)
    yield svc, ev, state
    srv.shutdown()


def _errs(ev):
    return [e for e in ev if e["type"] == "agent_error"]


def _schema_ok(e):
    assert set(e) == {"type", "code", "message", "detail", "fix_action", "retryable"}
    assert isinstance(e["code"], str) and e["message"] and isinstance(e["detail"], str)
    assert e["fix_action"] in (None, AgentService.FIX_SETTINGS, AgentService.FIX_RESEND)
    assert isinstance(e["retryable"], bool) and KEY not in e["message"] + e["detail"]


def test_malformed_tool_schema_emits_error_then_next_turn_works(svc_srv, monkeypatch):
    svc, ev, _ = svc_srv
    good = svc.loop.tools
    monkeypatch.setattr(svc.loop, "tools", lambda: [{"name": "bad", "description": "缺 input_schema"}])
    n = len(svc.loop.messages)
    r = svc.ask("你好")
    (e,) = _errs(ev)
    _schema_ok(e)
    assert e["code"] == "tool_schema" and "input_schema" in e["message"] and "Traceback" in e["detail"] and r
    assert len(svc.loop.messages) == n                                                # 本轮作废
    monkeypatch.setattr(svc.loop, "tools", good)
    ev.clear()
    assert svc.ask("再来一次") == "收到" and not _errs(ev)


def test_llm_403_emits_error_with_fix(svc_srv):
    svc, ev, state = svc_srv
    state["code"] = 403
    svc.ask("你好")
    (e,) = _errs(ev)
    _schema_ok(e)
    assert e["code"] == "llm_403" and "网关拒绝" in e["message"] and "DZ_LLM_API_KEY" in e["message"]
    assert e["fix_action"] == "llm_cfg" and e["detail"] == ""
    assert ev[-1]["type"] == "agent_unreachable"
    state["code"] = 200
    ev.clear()
    assert svc.ask("好了吗") == "收到" and not _errs(ev)


def test_unexpected_exception_is_internal(svc_srv, monkeypatch):
    svc, ev, _ = svc_srv
    monkeypatch.setattr(svc.loop, "condense", lambda: (_ for _ in ()).throw(RuntimeError(f"boom {KEY}")))
    svc.ask("x")
    (e,) = _errs(ev)
    _schema_ok(e)
    assert e["code"] == "internal" and e["retryable"] and e["fix_action"] == "agent_chat"


def _entry_ids():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[3]
    return set(re.findall(r"\{id:\s*([\w-]+)", (root / "docs/dev/entrypoints.yaml").read_text(encoding="utf-8")))


def _llm_err(code=None, down=False, retry=False, msg="x"):
    e = llm.LLMError(msg, "y", down=down)
    if code:
        e.code = code
    e.retry = retry
    return e


CASES = [_llm_err(c) for c in (401, 402, 403, 404, 429, 500, 503)] + [
    _llm_err(down=True, msg="连不上模型服务（请求超时）"), _llm_err(down=True, msg="连不上模型服务（网络不通或地址不对）"),
    _llm_err(msg="没有 API Key"), _llm_err(msg="其它"), KeyError("input_schema"), TimeoutError("t"), RuntimeError("r")]


@pytest.mark.parametrize("exc", CASES, ids=lambda e: type(e).__name__ + str(getattr(e, "code", "")))
def test_every_fix_action_is_an_entrypoint(svc_srv, exc):
    svc, ev, _ = svc_srv
    e = svc._agent_error(exc)
    _schema_ok(e)
    assert e["fix_action"] is None or e["fix_action"] in _entry_ids()
