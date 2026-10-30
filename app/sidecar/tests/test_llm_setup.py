"""首次接大模型：对本地假 OpenAI 兼容服务测“测试连接”（不保存）、401 报错带修法、保存后 configured。全离线。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dzbench.agent import llm


class _Mock(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Mock.seen.append((self.path, self.headers.get("Authorization"), body["model"]))
        if self.headers.get("Authorization") != "Bearer sk-good-123456":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":"invalid key"}'); return
        out = json.dumps({"choices": [{"message": {"role": "assistant", "content": "收到"}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def mock_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_first_run_setup_against_mock(mock_url, tmp_path, monkeypatch):
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path)); monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.delenv("DZBENCH_API_KEY", raising=False)
    monkeypatch.setattr(llm, "config_path", lambda: tmp_path / "config.json")
    assert llm.public_config()["configured"] is False
    form = {"provider": "custom", "base_url": mock_url, "model": "mock-1", "api_key": "sk-good-123456"}
    r = llm.test_connection(form)
    assert r["ok"] and r["reply"] == "收到" and r["model"] == "mock-1", r
    assert _Mock.seen[-1] == ("/v1/chat/completions", "Bearer sk-good-123456", "mock-1")
    assert not (tmp_path / "config.json").exists()           # 测试连接不写配置
    bad = llm.test_connection(form | {"api_key": "sk-wrong-000000"})
    assert not bad["ok"] and "401" in bad["message"] and "Key" in bad["fix"]
    down = llm.test_connection(form | {"base_url": "http://127.0.0.1:9/v1"})
    assert not down["ok"] and "连不上" in down["message"]
    pub = llm.save_config(form)
    assert pub["configured"] and pub["key_hint"] == "…3456" and "sk-good" not in json.dumps(pub)
    assert llm.test_connection({})["ok"]                      # 留空 Key = 用已保存的
