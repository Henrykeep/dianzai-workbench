"""OpenAI 兼容 Chat Completions 客户端（只用标准库）。

国内外主流服务都提供 OpenAI 兼容端点，所以一个客户端覆盖全部；换服务 = 换 base_url + model。
密钥只存本机 ~/.dzbench/config.json（权限 0600），环境变量 DZBENCH_API_KEY 优先；永远不写进仓库/日志/界面回显。
"""
from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request

PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "name": "DeepSeek"},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "name": "通义千问（百炼）"},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k", "name": "Kimi（月之暗面）"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash", "name": "智谱 GLM"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "name": "OpenAI"},
    "ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b", "name": "Ollama（本地，离线）"},
    "custom": {"base_url": "", "model": "", "name": "自定义 OpenAI 兼容"},
}


class LLMError(Exception):
    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.message, self.fix = message, fix


def config_path() -> pathlib.Path:
    from ..snapshots import base_dir
    return base_dir() / "config.json"


def load_config() -> dict:
    p = config_path()
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg.setdefault("provider", "deepseek")
    base = PROVIDERS.get(cfg["provider"], PROVIDERS["custom"])
    cfg.setdefault("base_url", base["base_url"])
    cfg.setdefault("model", base["model"])
    if os.environ.get("DZBENCH_API_KEY"):
        cfg["api_key"] = os.environ["DZBENCH_API_KEY"]
    return cfg


def save_config(update: dict) -> dict:
    cfg = load_config()
    if "provider" in update and update["provider"] != cfg.get("provider"):
        base = PROVIDERS.get(update["provider"], PROVIDERS["custom"])
        cfg.update(base_url=base["base_url"], model=base["model"])
    for k in ("provider", "base_url", "model", "api_key"):
        if k in update and (k != "api_key" or update[k]):     # 空 key 不覆盖已存的
            cfg[k] = update[k]
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({k: v for k, v in cfg.items() if k in ("provider", "base_url", "model", "api_key")}, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return public_config(cfg)


def public_config(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    k = cfg.get("api_key", "")
    return {"provider": cfg["provider"], "base_url": cfg["base_url"], "model": cfg["model"],
            "has_key": bool(k), "key_hint": ("…" + k[-4:]) if len(k) > 8 else "", "providers": PROVIDERS}


class OpenAICompat:
    def __init__(self, cfg: dict | None = None, timeout: float = 60):
        self.cfg = cfg or load_config()
        self.timeout = timeout

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """返回 assistant message（可能含 tool_calls）。"""
        c = self.cfg
        if not c.get("base_url"):
            raise LLMError("没有配置模型服务地址", "在 Agent 设置里选一个服务商")
        if not c.get("api_key") and c.get("provider") != "ollama":
            raise LLMError("没有 API Key", "在 Agent 设置里填 Key（只存在本机），或改用 Ollama 本地模型；离线时“分析阶跃”不需要 Key")
        body = {"model": c["model"], "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["input_schema"]}} for t in tools]
        req = urllib.request.Request(c["base_url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {c.get('api_key', 'ollama')}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")[:300]
            fix = {401: "Key 不对或过期", 402: "余额不足", 404: "模型名或地址不对", 429: "请求太频繁/额度用完，稍后再试"}.get(e.code, "")
            raise LLMError(f"模型服务返回 {e.code}：{txt}", fix) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(f"连不上模型服务：{e}", "比赛现场可能没网：用“分析阶跃”（离线规则）或本地 Ollama") from e
