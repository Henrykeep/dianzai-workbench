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
    assert r == {"ok": True, "models": ["deepseek-v4.1-flash", "glm-4"]}
    assert seen == [("/v1/models", f"Bearer {KEY}")]
    assert not llm.config_path().exists()                     # 只读，不写配置


@pytest.mark.parametrize("code,body", [(404, {"error": "not found"}), (405, {}), (200, b"<html>ok</html>"), (200, {"models": []}), (200, {"data": []})])
def test_unsupported_falls_back_to_manual(cfg, code, body):
    srv, url = _serve(lambda h: (code, body))
    try:
        r = llm.discover_models({"base_url": url, "api_key": KEY})
    finally:
        srv.shutdown()
    assert r["ok"] is False and r["models"] == [] and r["reason"] == "unsupported" and r["message"]
    assert llm.list_models({"base_url": url, "api_key": KEY}) == []


def test_errors_reported_without_leaking_key(cfg):
    srv, url = _serve(lambda h: (401, {"error": "invalid key"}))
    try:
        bad = llm.discover_models({"base_url": url, "api_key": KEY})
    finally:
        srv.shutdown()
    assert bad["reason"] == "error" and "401" in bad["message"] and "Key" in bad["message"]
    srv, url = _serve(lambda h: (503, {"error": "busy"}))
    try:
        five = llm.discover_models({"base_url": url, "api_key": KEY})
    finally:
        srv.shutdown()
    assert five["reason"] == "error" and "503" in five["message"]
    down = llm.discover_models({"base_url": "http://127.0.0.1:9/v1", "api_key": KEY})
    assert down["ok"] is False and down["reason"] == "error" and "无法连接" in down["message"]
    assert llm.discover_models({"base_url": "", "provider": "custom"})["reason"] == "error"
    for r in (bad, five, down):
        assert KEY not in json.dumps(r, ensure_ascii=False)
