"""首次配置的模型列表：对本地假 OpenAI 兼容服务测 GET /models 的列出、接口不支持、出错三种情况。全离线。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dzbench.agent import llm

KEY = "sk-mock-models-0001"


def _serve(route):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = route(self)
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(raw)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/v1"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    for k in ("DZ_LLM_API_KEY", "DZ_LLM_BASE_URL", "DZ_LLM_MODEL", "DZBENCH_API_KEY", "DZBENCH_BASE_URL", "DZBENCH_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm, "config_path", lambda: tmp_path / "config.json")


def _keys_ok(r):
    from dzbench.human_only import HUMAN_ONLY_KEYS
    want = llm.MODELS_KEYS | (HUMAN_ONLY_KEYS if r.get("fix_action") == "enable_cloud" else set())
    assert set(r) == want, set(r)                            # 返回键集合精确等于约定（docs/dev/events.md），没有 message；enable_cloud 另带 human_only/goto
    assert r["fix_action"] == (None if r["ok"] else llm.MODELS_FIX[r["reason"]])


def _log(tmp_path):
    p = tmp_path / "logs" / "llm_models.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_lists_model_ids_with_key(cfg):
    seen = []

    def route(h):
        seen.append((h.path, h.headers.get("Authorization")))
        return 200, {"object": "list", "data": [{"id": "glm-4"}, {"id": "deepseek-v4.1-flash"}, {"id": "glm-4"}, {"x": 1}]}
    srv, url = _serve(route)
    try:
        r = llm.discover_models({"provider": "custom", "base_url": url + "/", "api_key": KEY})
    finally:
        srv.shutdown()
    _keys_ok(r)
    assert r["ok"] is True and r["models"] == ["deepseek-v4.1-flash", "glm-4"] and r["reason"] is None
    assert seen == [("/v1/models", f"Bearer {KEY}")]
    assert not llm.config_path().exists()                     # 只读，不写配置


@pytest.mark.parametrize("code,body,reason", [(404, {"error": "not found"}, "unsupported"), (405, {}, "unsupported"), (501, {}, "unsupported"),
                                              (200, b"<html>ok</html>", "unsupported"), (200, {"models": []}, "unsupported"),
                                              (200, {"data": []}, "empty")])
def test_unsupported_or_empty_falls_back_to_manual(cfg, code, body, reason):
    srv, url = _serve(lambda h: (code, body))
    try:
        r = llm.discover_models({"base_url": url, "api_key": KEY})
        assert llm.list_models({"base_url": url, "api_key": KEY}) == []
    finally:
        srv.shutdown()
    _keys_ok(r)
    assert r["ok"] is False and r["models"] == [] and r["reason"] == reason and r["fix_action"] == "manual_model" and r["message_zh"]


@pytest.mark.parametrize("code,reason,fix", [(401, "auth", "check_key"), (403, "auth", "check_key"), (503, "error", "retry"), (500, "error", "retry")])
def test_http_errors_classified(cfg, tmp_path, code, reason, fix):
    srv, url = _serve(lambda h: (code, {"error": f"bad key {KEY} Bearer {KEY}"}))
    try:
        r = llm.discover_models({"base_url": url, "api_key": KEY})
    finally:
        srv.shutdown()
    _keys_ok(r)
    assert r["reason"] == reason and r["fix_action"] == fix and str(code) in r["message_zh"]
    assert KEY not in json.dumps(r, ensure_ascii=False) and KEY not in _log(tmp_path) and str(code) in _log(tmp_path)


def test_network_errors_category_only_and_redacted_log(cfg, tmp_path, monkeypatch):
    import socket
    import ssl
    import urllib.error
    cases = [(urllib.error.URLError(socket.timeout("timed out")), "连接超时"),
             (urllib.error.URLError(socket.gaierror(-2, "Name or service not known")), "DNS"),
             (urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")), "拒绝"),
             (urllib.error.URLError(ssl.SSLError(1, "CERTIFICATE_VERIFY_FAILED")), "TLS"),
             (OSError(f"weird failure Authorization: Bearer {KEY} sk-abcdefghijklmnop"), "网络错误")]
    for exc, zh in cases:
        def boom(*a, exc=exc, **k):
            raise exc
        monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
        r = llm.discover_models({"base_url": "https://api.example.com/v1", "api_key": KEY})
        _keys_ok(r)
        assert r["reason"] == "error" and r["fix_action"] == "retry" and zh in r["message_zh"], r
        assert "Errno" not in r["message_zh"] and "failure" not in r["message_zh"] and "refused" not in r["message_zh"]   # 不含原始异常
    log = _log(tmp_path)
    assert "weird failure" in log and KEY not in log and "sk-abcdefghijklmnop" not in log    # 原文脱敏后进本地日志


def test_contest_mode_blocks_before_request(cfg, tmp_path, monkeypatch):
    calls = []
    import urllib.error

    def fake(*a, **k):
        calls.append(a)
        raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    (tmp_path / "config.json").write_text(json.dumps({"contest_mode": True}), encoding="utf-8")
    r = llm.discover_models({"base_url": "https://api.example.com/v1", "api_key": KEY})
    _keys_ok(r)
    assert r["reason"] == "contest_mode" and r["fix_action"] == "enable_cloud" and calls == []     # 零调用
    assert r["human_only"] is True and r["goto"] == "settings:cloud"                               # 合规底线：只给跳转
    assert KEY not in json.dumps(r, ensure_ascii=False)
    for local in ("http://localhost:11434/v1", "http://127.0.0.1:11434/v1", "http://[::1]:11434/v1"):   # 本机不拦：照常请求
        assert llm.discover_models({"base_url": local})["reason"] != "contest_mode"
    assert len(calls) == 3
    calls.clear()
    (tmp_path / "config.json").write_text(json.dumps({"contest_mode": True, "cloud_enabled": True}), encoding="utf-8")
    assert llm.discover_models({"base_url": "https://api.example.com/v1", "api_key": KEY})["reason"] != "contest_mode" and len(calls) == 1


def test_server_agent_models_contest_mode_pushes_agent_error(cfg, tmp_path, monkeypatch, home):
    import asyncio
    from dzbench import server as srv
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该发请求")))
    (tmp_path / "config.json").write_text(json.dumps({"contest_mode": True}), encoding="utf-8")
    sv = srv.Server()
    sent = []

    async def bc(ev):
        sent.append(ev)
    sv._broadcast = bc
    r = asyncio.run(sv._op({"op": "agent_models", "form": {"base_url": "https://api.example.com/v1", "api_key": KEY}}))
    _keys_ok(r)
    assert r["reason"] == "contest_mode"
    ae = [e for e in sent if e["type"] == "agent_error" and e["code"] == "contest_mode"]
    assert len(ae) == 1 and set(ae[0]) == {"type", "code", "message_zh", "fix_action", "human_only", "goto", "retryable"}, ae   # 没有 message
    assert ae[0]["fix_action"] == "enable_cloud" and ae[0]["human_only"] is True and ae[0]["goto"] == "settings:cloud"
    assert KEY not in json.dumps(sent + [r], ensure_ascii=False)


def test_empty_url(cfg):
    r = llm.discover_models({"base_url": "", "provider": "custom"})
    _keys_ok(r)
    assert r["reason"] == "error"


def test_models_contract_documented():
    import pathlib
    doc = (pathlib.Path(__file__).resolve().parents[3] / "docs/dev/events.md").read_text(encoding="utf-8")
    for k in llm.MODELS_KEYS | set(llm.MODELS_FIX) | set(llm.MODELS_FIX.values()):
        assert f"`{k}`" in doc, k
