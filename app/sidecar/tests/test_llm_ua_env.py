"""llm.py：User-Agent、DZ_LLM_* 环境变量优先 + 旧名兼容、HTTP 错误按“原因 + 怎么解决”、密钥不回显。全离线。"""
import json

import pytest

from dzbench import __version__
from dzbench.agent import llm
from test_llm_client import serve

KEY = "sk-secret-ABCDEFG123456"


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("DZBENCH_API_KEY", "DZBENCH_BASE_URL", "DZBENCH_MODEL", "DZ_LLM_API_KEY", "DZ_LLM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm, "config_path", lambda: tmp_path / "config.json")
    return tmp_path


def _client(url, **kw):
    return llm.OpenAICompat({"provider": "custom", "base_url": url + "/v1", "model": "m", "api_key": KEY} | kw, retries=0, stream=False)


def test_user_agent_sent(env):
    seen = []
    srv, url, _ = serve(lambda h, b: (seen.append(h.headers.get("User-Agent")) or 200, "json",
                                      {"choices": [{"message": {"role": "assistant", "content": "收到"}}]}))
    try:
        _client(url).chat([{"role": "user", "content": "hi"}])
        llm.list_models({"base_url": url + "/v1", "api_key": KEY})
    finally:
        srv.shutdown()
    assert seen == [f"dzbench/{__version__}"] * 2


def test_env_precedence_and_legacy(env, monkeypatch, capsys):
    (env / "config.json").write_text(json.dumps({"provider": "custom", "base_url": "http://cfg/v1", "api_key": "sk-cfg"}))
    c = llm.load_config()
    assert c["base_url"] == "http://cfg/v1" and c["api_key"] == "sk-cfg"           # 没有环境变量：用 config.json
    monkeypatch.setenv("DZBENCH_API_KEY", "sk-legacy-xyz")
    llm._warned.clear()
    assert llm.load_config()["api_key"] == "sk-legacy-xyz"                           # 旧名兼容
    err = capsys.readouterr().err
    assert "DZBENCH_API_KEY" in err and "DZ_LLM_API_KEY" in err and "sk-legacy-xyz" not in err
    monkeypatch.setenv("DZ_LLM_API_KEY", "sk-new")
    monkeypatch.setenv("DZ_LLM_BASE_URL", "http://env/v1")
    c = llm.load_config()
    assert c["api_key"] == "sk-new" and c["base_url"] == "http://env/v1"             # 新名优先


@pytest.mark.parametrize("code,word", [(401, "密钥"), (403, "网关拒绝"), (404, "地址"), (429, "频繁"), (503, "故障")])
def test_http_errors_reason_fix_no_key(env, code, word):
    srv, url, _ = serve(lambda h, b: (code, "json", {"error": {"message": f"denied for key {KEY}"}}))
    try:
        with pytest.raises(llm.LLMError) as e:
            _client(url).chat([{"role": "user", "content": "hi"}])
    finally:
        srv.shutdown()
    assert str(code) in e.value.message and word in e.value.message and e.value.fix
    assert KEY not in e.value.message + e.value.fix
    if code == 403:
        assert "DZ_LLM_API_KEY" in e.value.fix and "DZ_LLM_BASE_URL" in e.value.fix


def test_network_error_message(env):
    with pytest.raises(llm.LLMError) as e:
        _client("http://127.0.0.1:9").chat([{"role": "user", "content": "hi"}])
    assert e.value.down and "连不上" in e.value.message and "DZ_LLM_BASE_URL" in e.value.fix and KEY not in e.value.message


def test_usage_on_reply_event(env):
    ev = []
    resp = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    srv, url, _ = serve(lambda h, b: (200, "json", resp | ({"usage": {"prompt_tokens": 7, "completion_tokens": 3}} if b["model"] == "t" else {})))
    try:
        for model in ("t", "n"):
            llm.OpenAICompat({"provider": "custom", "base_url": url + "/v1", "model": model, "api_key": KEY},
                             retries=0, stream=False, on_event=ev.append).chat([{"role": "user", "content": "hi"}])
    finally:
        srv.shutdown()
    u = [e["usage"] for e in ev if e["type"] == "agent_usage"]
    assert u[0]["tokens_in"] == 7 and u[0]["tokens_out"] == 3 and u[0]["elapsed_ms"] >= 0
    assert set(u[1]) == {"elapsed_ms"}
