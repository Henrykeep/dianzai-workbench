"""真大模型路径对本地假 OpenAI 兼容服务的测试（全离线）：流式 + 流式 tool_calls、JSON 兜底、重试退避、
token/费用、换模型列表、云端断了自动切本地 Ollama、检查/拉取 Ollama 模型、整条 Agent 循环走工具。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dzbench.agent import llm

TOOLS = [{"name": "read_telemetry", "description": "读遥测", "input_schema": {"type": "object", "properties": {"seconds": {"type": "number"}}}}]


def serve(script):
    """script(handler, body) -> (status, headers, bytes | list[dict] 作 SSE 块)。"""
    log = []

    class H(BaseHTTPRequestHandler):
        def _go(self, body):
            log.append((self.command, self.path, body))
            r = script(self, body)
            if r is None:          # 脚本自己写了响应（要发自定义头时）
                return
            st, kind, payload = r
            self.send_response(st)
            if kind == "sse":
                self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                for ch in payload:
                    self.wfile.write(b"data: " + json.dumps(ch).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(payload).encode())

        def do_POST(self):
            self._go(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))

        def do_GET(self):
            self._go(None)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}", log


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.delenv("DZBENCH_API_KEY", raising=False)
    monkeypatch.setattr(llm, "config_path", lambda: tmp_path / "config.json")
    return tmp_path


def cfg(url, **kw):
    return {"provider": "custom", "base_url": url + "/v1", "model": "m1", "api_key": "sk-x", "tool_mode": "auto"} | kw


def test_stream_text_and_tool_calls_with_usage_and_cost(cfgdir):
    def script(h, b):
        assert b["stream"] and b["tools"][0]["function"]["name"] == "read_telemetry"
        if len(b["messages"]) == 1:
            return 200, "sse", [
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_", "arguments": '{"sec'}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "telemetry", "arguments": 'onds": 2}'}}]}}]},
                {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 20}}]
        return 200, "sse", [{"choices": [{"delta": {"content": "超调 "}}]}, {"choices": [{"delta": {"content": "12%"}}]},
                            {"choices": [], "usage": {"prompt_tokens": 1200, "completion_tokens": 10}}]
    srv, url, _ = serve(script)
    ev = []
    c = llm.OpenAICompat(cfg(url, price_in=2, price_out=8), on_event=ev.append)
    m = c.chat([{"role": "user", "content": "看看"}], TOOLS)
    assert m["tool_calls"][0] == {"id": "c1", "type": "function", "function": {"name": "read_telemetry", "arguments": '{"seconds": 2}'}}
    m = c.chat([{"role": "user", "content": "看看"}, {"role": "assistant", "content": ""}], TOOLS)
    assert m["content"] == "超调 12%" and [e["text"] for e in ev if e["type"] == "agent_delta"] == ["超调 ", "12%"]
    u = [e for e in ev if e["type"] == "agent_usage"][-1]
    assert (u["prompt"], u["completion"]) == (2200, 30) and u["cost"] == pytest.approx((2200 * 2 + 30 * 8) / 1e6)
    srv.shutdown()


def test_no_price_means_no_cost(cfgdir):
    srv, url, _ = serve(lambda h, b: (200, "json", {"choices": [{"message": {"content": "好"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}))
    ev = []
    llm.OpenAICompat(cfg(url), on_event=ev.append).chat([{"role": "user", "content": "x"}])
    assert ev[-1]["cost"] is None and ev[-1]["prompt"] == 5      # 不编价格
    srv.shutdown()


def test_json_fallback_when_tools_rejected(cfgdir):
    """服务回 400 不认 tools → 自动改 JSON 兜底：工具表进 system、tool 结果改成 user 文本，模型回 JSON 也认成 tool_calls。"""
    def script(h, b):
        if "tools" in b:
            return 400, "json", {"error": {"message": "this model does not support tools"}}
        assert "调用工具的格式" in b["messages"][0]["content"] and all(m["role"] != "tool" for m in b["messages"])
        return 200, "json", {"choices": [{"message": {"content": '好的\n```json\n{"tool": "read_telemetry", "args": {"seconds": 1}}\n```'}}]}
    srv, url, log = serve(script)
    ev = []
    c = llm.OpenAICompat(cfg(url), on_event=ev.append, stream=False)
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "read_telemetry", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "{}"}]
    m = c.chat(msgs, TOOLS)
    assert json.loads(m["tool_calls"][0]["function"]["arguments"]) == {"seconds": 1}
    assert c.json_mode and {"type": "agent_toolmode", "mode": "json", "model": "m1"} in ev and len(log) == 2
    srv.shutdown()


def test_unknown_tool_in_json_is_plain_text():
    assert llm.parse_json_call('{"tool": "rm_rf", "args": {}}', {"read_telemetry"}) == []
    assert llm.parse_json_call("超调 {约 12%}", {"read_telemetry"}) == []
    assert llm.parse_json_call('{"name": "read_telemetry", "arguments": "{\\"seconds\\": 3}"}', {"read_telemetry"})[0]["function"]["arguments"] == '{"seconds": 3}'


def test_retry_with_backoff_on_503_then_ok(cfgdir):
    n = {"k": 0}

    def script(h, b):
        n["k"] += 1
        return (503, "json", {"error": "busy"}) if n["k"] < 3 else (200, "json", {"choices": [{"message": {"content": "ok"}}]})
    srv, url, _ = serve(script)
    ev = []
    assert llm.OpenAICompat(cfg(url), on_event=ev.append, stream=False, backoff=0.01).chat([{"role": "user", "content": "x"}])["content"] == "ok"
    assert [e["attempt"] for e in ev if e["type"] == "agent_retry"] == [1, 2]
    srv.shutdown()


def test_401_is_not_retried(cfgdir):
    srv, url, log = serve(lambda h, b: (401, "json", {"error": {"message": "bad key"}}))
    with pytest.raises(llm.LLMError) as e:
        llm.OpenAICompat(cfg(url), stream=False, backoff=0.01).chat([{"role": "user", "content": "x"}])
    assert "bad key" in e.value.message and not e.value.down and len(log) == 1
    srv.shutdown()


def test_failover_cloud_down_switches_to_local_ollama(cfgdir):
    """云端地址没人听 → 切本地（假 Ollama）；界面收到 agent_mode=local 和原因；之后一直用本地。"""
    srv, url, log = serve(lambda h, b: (200, "json", {"choices": [{"message": {"content": f"本地 {b['model']}"}}]}))
    llm.save_config(cfg("http://127.0.0.1:9", local_url=url + "/v1", local_model="qwen2.5:7b-instruct"))
    ev = []
    f = llm.build(emit=ev.append)
    f.primary.backoff = 0.01
    assert f.chat([{"role": "user", "content": "x"}])["content"] == "本地 qwen2.5:7b-instruct"
    assert ev[-1]["type"] == "agent_mode" and ev[-1]["mode"] == "local" and "连不上" in ev[-1]["fallback"]
    f.chat([{"role": "user", "content": "y"}])
    assert f.name == "qwen2.5:7b-instruct" and len(log) == 2
    srv.shutdown()


def test_failover_not_on_auth_error(cfgdir):
    cloud, curl, _ = serve(lambda h, b: (401, "json", {"error": {"message": "bad key"}}))
    local, lurl, llog = serve(lambda h, b: (200, "json", {"choices": [{"message": {"content": "x"}}]}))
    llm.save_config(cfg(curl, local_url=lurl + "/v1"))
    with pytest.raises(llm.LLMError):
        llm.build().chat([{"role": "user", "content": "x"}])
    assert llog == []                     # Key 错了要人修，不悄悄换模型
    cloud.shutdown(); local.shutdown()


def test_models_list_and_ollama_check_pull(cfgdir):
    def script(h, b):
        if h.path == "/v1/models":
            return 200, "json", {"data": [{"id": "m2"}, {"id": "m1"}]}
        if h.path == "/api/tags":
            return 200, "json", {"models": [{"name": "qwen2.5:7b-instruct"}]}
        if h.path == "/api/pull":
            assert b == {"model": "qwen3:8b", "stream": False}
            return 200, "json", {"status": "success"}
        return 404, "json", {}
    srv, url, _ = serve(script)
    assert llm.list_models({"base_url": url + "/v1", "api_key": "k"}) == ["m1", "m2"]
    assert llm.ollama("check", host=url) == {"ok": True, "running": True, "models": ["qwen2.5:7b-instruct"]}
    assert llm.ollama("pull", "qwen3:8b", host=url)["ok"]
    assert not llm.ollama("check", host="http://127.0.0.1:9")["running"]
    srv.shutdown()


def test_agent_loop_through_mock_with_tool_call(cfgdir, home, tmp_path):
    """整条 Agent：假服务先要 list_params（流式 tool_calls），工作台真跑工具，再给出引用数字的回答。"""
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    from dzbench.session import Session

    def script(h, b):
        if not any(m["role"] == "tool" for m in b["messages"]):
            return 200, "sse", [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "t1", "function": {"name": "list_params", "arguments": "{}"}}]}}]}]
        return 200, "sse", [{"choices": [{"delta": {"content": "现在没有参数（0 个），先连板子。"}}]}]
    srv, url, _ = serve(script)
    llm.save_config(cfg(url))
    ev = []
    s = Session()
    svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path)
    r = svc.ask("当前参数？")
    assert "0 个" in r and any(e["type"] == "agent_tool" and e["name"] == "list_params" for e in ev)
    assert {"type": "agent_mode", "mode": "llm", "name": "m1"} in ev
    srv.shutdown()


# ---------------------------------------------------------------- 第一次真模型评测暴露的问题（2026-10，经 OpenAI 兼容中转站）
def test_sends_own_user_agent(cfgdir):
    """Cloudflare 后面的中转站对默认 "Python-urllib" UA 直接 403（error code 1010）。"""
    seen = []

    def script(h, b):
        seen.append(h.headers.get("User-Agent", ""))
        return 200, "json", {"choices": [{"message": {"role": "assistant", "content": "收到"}}]}
    srv, url, _ = serve(script)
    llm.OpenAICompat(cfg(url), stream=False).chat([{"role": "user", "content": "hi"}])
    srv.shutdown()
    assert seen and "urllib" not in seen[0].lower()


def test_think_block_hidden_and_does_not_break_json_fallback(cfgdir):
    """推理模型把 <think>…</think> 写进正文：不推给界面，JSON 兜底也要越过思考里的花括号认出调用。"""
    content = '<think>用户要遥测，参数形如 {seconds}</think>\n{"tool": "read_telemetry", "args": {"seconds": 2}}'
    srv, url, _ = serve(lambda h, b: (200, "sse", [{"choices": [{"delta": {"content": content[:20]}}]},
                                                    {"choices": [{"delta": {"content": content[20:]}}]}]))
    ev = []
    m = llm.OpenAICompat(cfg(url, tool_mode="json"), on_event=ev.append).chat([{"role": "user", "content": "x"}], TOOLS)
    srv.shutdown()
    assert m["tool_calls"][0]["function"]["name"] == "read_telemetry"
    assert not any("think" in e.get("text", "") or "用户要遥测" in e.get("text", "") for e in ev if e["type"] == "agent_delta")
    assert llm.strip_think("<think>a</think>答案") == "答案"


def test_429_waits_retry_after_and_shows_clean_message(cfgdir, monkeypatch):
    waits, n = [], {"k": 0}
    monkeypatch.setattr(llm.time, "sleep", waits.append)

    def script(h, b):
        n["k"] += 1
        if n["k"] == 1:
            h.send_response(429); h.send_header("Retry-After", "3"); h.send_header("Content-Type", "application/json"); h.end_headers()
            h.wfile.write(json.dumps({"error": {"message": "1分钟内最多请求15次 " + "x" * 400}}).encode())
            return None
        return 200, "json", {"choices": [{"message": {"role": "assistant", "content": "好"}}]}
    srv, url, _ = serve(script)
    ev = []
    m = llm.OpenAICompat(cfg(url), stream=False, retries=2, on_event=ev.append).chat([{"role": "user", "content": "x"}])
    srv.shutdown()
    assert m["content"] == "好" and waits == [3.0]
    assert next(e for e in ev if e["type"] == "agent_retry")["why"].startswith("模型服务返回 429：1分钟内")


def test_native_tools_refused_with_zero_retries_still_falls_back(cfgdir):
    """以前“不认 tools → 改 JSON”占掉一次重试：retries=0（测试连接）时直接 UnboundLocalError。"""
    def script(h, b):
        if "tools" in b:
            return 400, "json", {"error": {"message": "tools not supported"}}
        return 200, "json", {"choices": [{"message": {"role": "assistant", "content": '{"tool": "read_telemetry", "args": {}}'}}]}
    srv, url, _ = serve(script)
    m = llm.OpenAICompat(cfg(url), stream=False, retries=0).chat([{"role": "system", "content": "s"}, {"role": "user", "content": "x"}], TOOLS)
    srv.shutdown()
    assert m["tool_calls"][0]["function"]["name"] == "read_telemetry"


def test_env_overrides_for_any_openai_compatible_relay(cfgdir, monkeypatch):
    monkeypatch.setenv("DZBENCH_BASE_URL", "https://relay.example/v1")
    monkeypatch.setenv("DZBENCH_MODEL", "some-flash")
    c = llm.load_config()
    assert (c["provider"], c["base_url"], c["model"]) == ("custom", "https://relay.example/v1", "some-flash")
