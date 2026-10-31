"""OpenAI 兼容 Chat Completions 客户端（只用标准库）。

国内外主流服务都提供 OpenAI 兼容端点，所以一个客户端覆盖全部；换服务 = 换 base_url + model。
密钥只存本机 ~/.dzbench/config.json（权限 0600），环境变量 DZ_LLM_API_KEY / DZ_LLM_BASE_URL 优先
（旧名 DZBENCH_API_KEY 兼容一个版本）；永远不写进仓库/日志/界面回显。

可靠性：流式输出（逐字推给界面）、429/5xx/断网指数退避重试、token 用量上报（填了单价才算钱，不编价格）、
不支持原生 tool_calls 的模型走 JSON 兜底（工具表写进提示词，模型回一段 JSON）、云端连不上自动切本地 Ollama。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .. import __version__

USER_AGENT = f"dzbench/{__version__}"     # 有的网关（Cloudflare 1010）拒绝 urllib 默认 UA
_warned: set[str] = set()


def _deprecate(old: str, new: str) -> None:
    """旧配置名提示一次（只说名字，不带值）。"""
    if old not in _warned:
        _warned.add(old)
        import sys
        print(f"[dzbench] {old} 已弃用，下个版本移除；请改用 {new}", file=sys.stderr)

PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "name": "DeepSeek"},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "name": "通义千问（百炼）"},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k", "name": "Kimi（月之暗面）"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash", "name": "智谱 GLM"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct", "name": "硅基流动"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "name": "OpenAI"},
    "ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b-instruct", "name": "Ollama（本地，离线）"},
    "custom": {"base_url": "", "model": "", "name": "自定义 OpenAI 兼容"},
}
# 本地推荐：小尺寸里工具调用靠谱的（Ollama 模型名）。只是推荐清单，不代表跑分。
LOCAL_MODELS = [
    {"model": "qwen2.5:7b-instruct", "size": "≈4.7 GB", "note": "推荐：7B 里工具调用最稳，8 GB 显存/16 GB 内存可跑"},
    {"model": "qwen3:8b", "size": "≈5.2 GB", "note": "更新一代，工具调用好；稍慢"},
    {"model": "qwen2.5:3b-instruct", "size": "≈1.9 GB", "note": "轻薄本也能跑；复杂任务会走 JSON 兜底"},
]
KEYS = ("provider", "base_url", "model", "api_key", "repo", "local_model", "local_url", "failover", "tool_mode", "price_in", "price_out")


class LLMError(Exception):
    def __init__(self, message: str, fix: str = "", down: bool = False):
        super().__init__(message)
        self.message, self.fix, self.down = message, fix, down     # down=连不上（可切本地）


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
    cfg.setdefault("local_model", PROVIDERS["ollama"]["model"])
    cfg.setdefault("failover", True)
    cfg.setdefault("tool_mode", "auto")
    if os.environ.get("DZ_LLM_API_KEY"):
        cfg["api_key"] = os.environ["DZ_LLM_API_KEY"]
    elif os.environ.get("DZBENCH_API_KEY"):          # 旧名：兼容一个版本
        _deprecate("DZBENCH_API_KEY", "DZ_LLM_API_KEY")
        cfg["api_key"] = os.environ["DZBENCH_API_KEY"]
    if os.environ.get("DZ_LLM_BASE_URL"):
        cfg.update(provider="custom", base_url=os.environ["DZ_LLM_BASE_URL"])
    elif os.environ.get("DZBENCH_BASE_URL"):
        _deprecate("DZBENCH_BASE_URL", "DZ_LLM_BASE_URL")
        cfg.update(provider="custom", base_url=os.environ["DZBENCH_BASE_URL"])
    if os.environ.get("DZ_LLM_MODEL"):              # 模型名：环境变量 > config.json > 服务商默认
        cfg["model"] = os.environ["DZ_LLM_MODEL"]
    elif os.environ.get("DZBENCH_MODEL"):
        _deprecate("DZBENCH_MODEL", "DZ_LLM_MODEL")
        cfg["model"] = os.environ["DZBENCH_MODEL"]
    return cfg


def _redact(text: str, key: str) -> str:
    text = text.replace(key, "***") if key and len(key) >= 4 else text
    return re.sub(r"(sk-|Bearer\s+)[A-Za-z0-9_\-\.]{6,}", r"\1***", text)


ENV_HINT = "检查 DZ_LLM_API_KEY / DZ_LLM_BASE_URL（或大模型设置里的 Key 和地址）"


def http_error(code: int, detail: str, key: str = "") -> "LLMError":
    """HTTP 错误 → “原因 + 怎么解决”。detail 是服务端原话（已去密钥），附在原因后面方便排查。"""
    if code == 401:
        why, fix = "密钥无效或已过期", f"Key 不对或过期：{ENV_HINT}"
    elif code == 402:
        why, fix = "账户余额不足", "到服务商控制台充值，或改用本地 Ollama"
    elif code == 403:
        why, fix = "网关拒绝请求，可能是密钥无效、没有该模型权限或被网关拦截", ENV_HINT + "；仍不行就换个服务地址或联系服务商"
    elif code == 404:
        why, fix = "地址或模型名不对", "地址一般以 /v1 结尾；检查 DZ_LLM_BASE_URL 和模型名"
    elif code == 429:
        why, fix = "请求太频繁或额度用完", "稍后再试，或到服务商控制台查看额度"
    elif code >= 500:
        why, fix = "模型服务暂时故障", "稍后重试；持续出错就换服务商或切本地 Ollama"
    else:
        why, fix = "请求被拒绝", "检查模型名和参数；" + ENV_HINT
    detail = _redact(detail, key).strip()
    return LLMError(f"模型服务返回 {code}：" + (f"{detail[:200]}（{why}）" if detail else why), fix)


def save_config(update: dict) -> dict:
    cfg = load_config()
    if "provider" in update and update["provider"] != cfg.get("provider"):
        base = PROVIDERS.get(update["provider"], PROVIDERS["custom"])
        cfg.update(base_url=base["base_url"], model=base["model"])
    for k in KEYS:                                   # 只认 KEYS：contest_mode / cloud_enabled（GUARDED_KEYS）传了也忽略
        if k in update and (k != "api_key" or update[k]):     # 空 key 不覆盖已存的
            cfg[k] = update[k]
    p = config_path()
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    _write_raw({k: v for k, v in cfg.items() if k in KEYS} | {k: old[k] for k in GUARDED_KEYS if k in old})   # 合规开关原样保留
    return public_config(cfg)


def public_config(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    k = cfg.get("api_key", "")
    return {**{x: cfg.get(x) for x in KEYS if x != "api_key"}, "repo": cfg.get("repo", ""),
            "has_key": bool(k), "key_hint": ("…" + k[-4:]) if len(k) > 8 else "", "providers": PROVIDERS, "local_models": LOCAL_MODELS,
            "configured": bool(k or cfg["provider"] == "ollama")}     # 环境变量里有 Key 就算配好，不要求 config.json（r6 #21）


def local_config(cfg: dict) -> dict:
    """云端连不上时切的本地模型（Ollama，同一套 OpenAI 兼容接口）。"""
    return {**cfg, "provider": "ollama", "base_url": cfg.get("local_url") or PROVIDERS["ollama"]["base_url"], "model": cfg.get("local_model") or PROVIDERS["ollama"]["model"],
            "api_key": "", "price_in": None, "price_out": None}


def _req(url: str, body: dict | None = None, key: str = "", timeout: float = 15):
    # 带上自己的 User-Agent：不少中转站（Cloudflare 后面）直接 403 拦默认的 "Python-urllib"（error code 1010）
    h = {"Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json, text/event-stream"} | ({"Authorization": f"Bearer {key}"} if key else {})
    return urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h), timeout=timeout)


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MODELS_KEYS = {"ok", "models", "reason", "fix_action", "message_zh"}   # agent_models 返回约定（docs/dev/events.md）
MODELS_FIX = {"unsupported": "manual_model", "empty": "manual_model", "auth": "check_key", "error": "retry", "contest_mode": "enable_cloud"}
_NET_ZH = {"timeout": "连接超时", "dns": "域名解析失败（DNS）", "refused": "连接被拒绝", "tls": "TLS/证书握手失败", "other": "网络错误"}


def _is_local(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in LOCAL_HOSTS


def contest_blocks_cloud(cfg: dict) -> bool:
    """比赛模式且没启用云端 → 不许连外部服务。
    TODO(contest_mode)：contest_mode 还没有设置入口，暂读 ~/.dzbench/config.json；cloud_enabled 只能经 set_cloud_enabled(confirmed=True) 改。"""
    return bool(cfg.get("contest_mode")) and not cfg.get("cloud_enabled", False)


def _net_kind(e: BaseException) -> str:
    r = getattr(e, "reason", e)
    txt = f"{type(r).__name__} {r}".lower()
    if isinstance(r, (TimeoutError, socket.timeout)) or "timed out" in txt:
        return "timeout"
    if isinstance(r, socket.gaierror) or "name or service" in txt or "getaddrinfo" in txt or "nodename" in txt:
        return "dns"
    if isinstance(r, ConnectionRefusedError) or "refused" in txt:
        return "refused"
    if isinstance(r, ssl.SSLError) or "ssl" in txt or "certificate" in txt or "tls" in txt:
        return "tls"
    return "other"


def _models_log(line: str, key: str) -> None:
    """原始报错只进本地日志（先脱敏），不回给界面。"""
    try:
        d = config_path().parent / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "llm_models.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%S%z ") + _redact(line, key).replace("\n", " ")[:500] + "\n")
    except OSError:
        pass


def _models_fail(reason: str, message_zh: str) -> dict:
    r = {"ok": False, "models": [], "reason": reason, "fix_action": MODELS_FIX[reason], "message_zh": message_zh}
    if r["fix_action"] == "enable_cloud":          # 合规底线：启用云端只能由人做 → human_only + goto settings:cloud
        from ..human_only import mark
        r = mark(r, "enable_cloud")
    return r


# 合规开关：不在 KEYS 里，save_config / agent_config 改不动（但会原样保留）；唯一写入口是 set_cloud_enabled(confirmed=True)
GUARDED_KEYS = ("contest_mode", "cloud_enabled")


def set_cloud_enabled(enabled: bool, confirmed=False) -> dict:
    """比赛模式下启用 / 关闭云端。只能由人：界面确认卡确认后带 confirmed=True 调用（op set_cloud_enabled）。
    Agent 工具表、script_ops、自动流程都不得调用这里（tests/test_cloud_guard.py 守着）。"""
    from ..human_only import require_confirmed
    nc = require_confirmed(confirmed, "启用云端需要确认：比赛模式下启用后会把数据发往外部模型服务" if enabled else "关闭云端需要确认")
    if nc:
        return nc
    p = config_path()
    raw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    raw["cloud_enabled"] = bool(enabled)
    _write_raw(raw)
    return {"ok": True, "cloud_enabled": bool(enabled), "message_zh": "已启用云端" if enabled else "已关闭云端"}


def _write_raw(raw: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def discover_models(form: dict, timeout: float = 8) -> dict:
    """首次配置：GET {base_url}/models（OpenAI 兼容）列出可选模型。

    返回 {ok, models, reason, fix_action, message_zh}（键集合 MODELS_KEYS；成功时 reason/fix_action 为 None）：
    unsupported（404/405/501/非 OpenAI 格式）、empty（列表为空）→ manual_model；auth（401/403）→ check_key；
    error（其他 HTTP / 网络）→ retry；contest_mode（比赛模式未启用云端且地址非本机，不发请求）→ enable_cloud。
    文案只按类别给中文，不含原始异常与 Key；原文脱敏后写本地日志。
    """
    cfg = load_config() | {k: v for k, v in form.items() if v}
    key = cfg.get("api_key", "") or ""
    url = (str(form["base_url"]) if "base_url" in form else cfg.get("base_url") or "").strip().rstrip("/")   # 表单里给了（哪怕空）就以表单为准
    if url and not _is_local(url) and contest_blocks_cloud(cfg):     # 先判，再拼 URL / 发请求
        return _models_fail("contest_mode", "比赛模式下未启用云端，不请求外部服务；请手动填写模型名或启用云端。")
    if not url:
        return _models_fail("error", "未填写接口地址。")
    try:
        with _req(url + "/models", key=key, timeout=timeout) as r:
            data = json.loads(r.read())
        ids = sorted({str(m["id"]) for m in data["data"] if isinstance(m, dict) and m.get("id")})
    except urllib.error.HTTPError as e:
        _models_log(f"GET /models HTTP {e.code} {e.reason}", key)
        if e.code in (404, 405, 501):
            return _models_fail("unsupported", f"该服务未提供模型列表接口（HTTP {e.code}）。")
        if e.code in (401, 403):
            return _models_fail("auth", f"鉴权失败（HTTP {e.code}），请检查 API Key。")
        return _models_fail("error", f"获取模型列表失败（HTTP {e.code}）。")
    except (KeyError, TypeError, ValueError) as e:
        _models_log(f"GET /models 非 OpenAI 格式 {type(e).__name__}: {e}", key)
        return _models_fail("unsupported", "该服务的模型列表响应不符合 OpenAI 格式。")
    except (OSError, urllib.error.URLError) as e:
        k = _net_kind(e)
        _models_log(f"GET /models 网络错误 [{k}] {type(e).__name__}: {getattr(e, 'reason', e)}", key)
        return _models_fail("error", f"无法连接服务：{_NET_ZH[k]}。")
    if not ids:
        return _models_fail("empty", "该服务返回的模型列表为空。")
    return {"ok": True, "models": ids, "reason": None, "fix_action": None, "message_zh": f"已获取 {len(ids)} 个可用模型。"}


def list_models(form: dict) -> list[str]:
    """兼容旧调用：只要模型 id 列表，失败返回空表。"""
    return discover_models(form)["models"]


def ollama(action: str, model: str = "", host: str = "") -> dict:
    """一键“检查 Ollama 并拉模型”：check → 在不在跑、装了哪些模型；pull → 让 Ollama 下载（阻塞到下完）。"""
    host = host or re.sub(r"/v1/?$", "", load_config().get("local_url") or PROVIDERS["ollama"]["base_url"])
    try:
        if action == "pull":
            with _req(host + "/api/pull", {"model": model, "stream": False}, timeout=3600) as r:
                st = json.loads(r.read()).get("status", "")
            return {"ok": st == "success", "status": st}
        with _req(host + "/api/tags", timeout=4) as r:
            have = [m["name"] for m in json.loads(r.read()).get("models", [])]
        return {"ok": True, "running": True, "models": have}
    except (OSError, ValueError, urllib.error.URLError) as e:
        return {"ok": False, "running": False, "message": f"连不上 Ollama（{host}）：{e}", "fix": "装 Ollama（ollama.com）并启动；Windows 装完会在托盘常驻"}


def test_connection(form: dict, timeout: float = 15) -> dict:
    """用表单里（还没保存）的地址/模型/Key 发一句最小的对话，回报通不通、多久、模型回了什么。不写配置。"""
    cfg = load_config()
    for k in ("provider", "base_url", "model", "api_key"):
        if form.get(k):
            cfg[k] = form[k]
    t0 = time.monotonic()
    try:
        m = OpenAICompat(cfg, timeout=timeout, retries=0, stream=False).chat([{"role": "user", "content": "只回复两个字：收到"}])
    except LLMError as e:
        return {"ok": False, "message": e.message, "fix": e.fix}
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return {"ok": False, "message": f"接口回的不是 OpenAI 格式：{e!r}"[:200], "fix": "地址一般以 /v1 结尾；确认服务商支持 /chat/completions"}
    return {"ok": True, "model": cfg["model"], "ms": round((time.monotonic() - t0) * 1000), "reply": str(m.get("content") or "")[:80]}


# ------------------------------------------------------------------ JSON 兜底（模型不支持原生 tool_calls）
JSON_RULE = ("\n\n## 调用工具的格式\n你没有原生工具调用。要用工具时，整条回复只写一个 JSON 对象："
             '{"tool": "工具名", "args": {参数}}，不要别的字。工具结果会以“[工具结果 名字]”发回给你。'
             "不需要工具时直接用中文回答。可用工具：\n")


def to_json_mode(messages: list[dict], tools: list[dict] | None) -> list[dict]:
    """把含 tool_calls / tool 角色的对话改写成纯文本对话，工具表追加进 system。"""
    out = []
    for m in messages:
        if m["role"] == "system" and tools:
            spec = "\n".join(f"- {t['name']}：{t['description'][:160]} 参数 {json.dumps(t['input_schema'].get('properties', {}), ensure_ascii=False)[:300]}" for t in tools)
            out.append({"role": "system", "content": m["content"] + JSON_RULE + spec})
        elif m["role"] == "tool":
            out.append({"role": "user", "content": f"[工具结果 {m.get('tool_call_id', '')}]\n{m['content']}"})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            c = m["tool_calls"][0]["function"]
            out.append({"role": "assistant", "content": json.dumps({"tool": c["name"], "args": json.loads(c.get("arguments") or "{}")}, ensure_ascii=False)})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


THINK = re.compile(r"<think>.*?(</think>|$)", re.S)


def strip_think(text: str) -> str:
    """推理模型（GLM/Qwen3/DeepSeek-R 系）常把思考过程用 <think>…</think> 写进正文：不给用户看，也别挡住 JSON 兜底。"""
    return THINK.sub("", text or "").strip()


def parse_json_call(content: str, names: set[str]) -> list[dict]:
    """从文本里认出工具调用：{"tool":..,"args":..} 或 {"name":..,"arguments":..}，可裹在 ```json 里、前后有别的字。
    逐个 "{" 试着解析（以前用贪婪正则从第一个 { 抓到最后一个 }，正文里有别的花括号就整段失败）。认不出返回 []。"""
    text, dec = strip_think(content), json.JSONDecoder()
    for i in (k for k, ch in enumerate(text) if ch == "{"):
        try:
            d, _ = dec.raw_decode(text, i)
        except ValueError:
            continue
        name = (d.get("tool") or d.get("name")) if isinstance(d, dict) else None
        if name not in names:
            continue
        args = d.get("args", d.get("arguments", d.get("parameters", {})))
        try:
            args = json.loads(args) if isinstance(args, str) else args
        except ValueError:
            continue
        return [{"id": f"j_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {}, ensure_ascii=False)}}]
    return []


# ------------------------------------------------------------------ 客户端
class OpenAICompat:
    RETRY_CODES = (429, 500, 502, 503, 504)
    RETRIES_5XX = 4                                   # 502/503/504 的重试上限（退避 0.8→1.6→3.2→6.4 s，约 12 s 后给出明确错误）

    def __init__(self, cfg: dict | None = None, timeout: float = 60, on_event: Callable[[dict], None] | None = None,
                 retries: int = 2, stream: bool = True, backoff: float = 0.8):
        self.cfg = cfg or load_config()
        self.timeout, self.retries, self.stream, self.backoff = timeout, retries, stream, backoff
        self.emit = on_event or (lambda e: None)
        self.json_mode = self.cfg.get("tool_mode") == "json"
        self.name = self.cfg.get("model", "")
        self.usage = {"prompt": 0, "completion": 0}

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """返回 assistant message（可能含 tool_calls，JSON 兜底时也统一成 tool_calls）。"""
        c = self.cfg
        if not c.get("base_url"):
            raise LLMError("没有配置模型服务地址", "在大模型设置里选一个服务商")
        if not c.get("api_key") and c.get("provider") != "ollama":
            raise LLMError("没有 API Key", "在大模型设置里填 Key（只存在本机），或改用本地 Ollama")
        attempt = 0
        while True:
            try:
                m = self._once(messages, tools)
                break
            except LLMError as e:
                native_refused = not self.json_mode and tools and "400" in e.message and "tool" in e.message.lower()
                if native_refused:                          # 服务/模型不认 tools 参数 → 以后都走 JSON 兜底（不占重试次数）
                    self.json_mode = True
                    self.emit({"type": "agent_toolmode", "mode": "json", "model": self.name})
                    continue
                code = getattr(e, "code", 0) or 0
                # 503/502/504（服务商暂时没有可用节点，如 r8 llm_503 “No provider … available”）多给两次、退避更长
                limit = max(self.retries, self.RETRIES_5XX) if self.retries and code in (502, 503, 504) else self.retries
                if attempt >= limit or not getattr(e, "retry", False):
                    if attempt and getattr(e, "retry", False):
                        e.message += f"（已自动重试 {attempt} 次仍失败）"
                    raise
                # 限流（429）按服务给的 Retry-After 等；没给就按“每分钟 N 次”这类窗口等够几秒，不再 0.8 s 就重撞
                wait = getattr(e, "retry_after", None) or (8.0 * (attempt + 1) if code == 429 else self.backoff * (2 ** attempt))
                wait = min(float(wait), 30.0)
                attempt += 1
                what = (f"模型服务暂时不可用（HTTP {code}）" if code >= 500 else "模型服务限流（HTTP 429）" if code == 429
                        else "连不上模型服务")
                self.emit({"type": "agent_retry", "attempt": attempt, "max": limit, "wait_s": wait, "code": code or None,
                           "why": e.message[:120],
                           "message_zh": f"{what}，{wait:g} 秒后自动重试（第 {attempt}/{limit} 次），不用重发"})
                time.sleep(wait)
        if tools and not m.get("tool_calls") and (calls := parse_json_call(m.get("content") or "", {t["name"] for t in tools})):
            m = {"role": "assistant", "content": "", "tool_calls": calls}      # 小模型常把调用写进正文：也认
        m["content"] = strip_think(m.get("content") or "")
        return m

    def _once(self, messages: list[dict], tools: list[dict] | None) -> dict:
        c = self.cfg
        msgs = to_json_mode(messages, tools) if self.json_mode else messages
        body = {"model": c["model"], "messages": msgs, "temperature": 0.2}
        if tools and not self.json_mode:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["input_schema"]}} for t in tools]
        if self.stream:
            body |= {"stream": True, "stream_options": {"include_usage": True}}
        t0 = time.monotonic()
        try:
            with _req(c["base_url"].rstrip("/") + "/chat/completions", body, c.get("api_key") or "ollama", self.timeout) as r:
                if "text/event-stream" in (r.headers.get("Content-Type") or ""):
                    m, usage = self._read_stream(r)
                else:
                    d = json.loads(r.read())
                    m, usage = d["choices"][0]["message"], d.get("usage")
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            try:     # 多数服务回 {"error":{"message":…}}：只给人看那句话（先整段解析再截断，以前先截断导致长错误解析失败、原样糊给用户）
                err = json.loads(txt).get("error")
                txt = (err.get("message") if isinstance(err, dict) else err) or txt
            except (ValueError, AttributeError):
                pass
            err = http_error(e.code, str(txt), c.get("api_key") or "")
            if e.code in (404, 503) and c.get("provider") == "custom":     # 自定义中转站：404/503 多半是这家没有这个模型名（r6 #21）
                err.message += f"。模型名 {c.get('model')} 可能在这个服务上不存在"
                err.fix = ("在大模型设置里改模型名，或设环境变量 DZ_LLM_MODEL=<该服务支持的模型名>（优先级：环境变量 > 设置 > 默认）；"
                           "服务商控制台/模型列表里可查可用模型")
                err.model_hint = True
            err.retry, err.code = e.code in self.RETRY_CODES, e.code
            ra = (e.headers.get("Retry-After") or "") if e.headers else ""
            err.retry_after = float(ra) if ra.replace(".", "", 1).isdigit() else None
            raise err from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            kind = "请求超时" if isinstance(reason, TimeoutError) or "timed out" in str(reason) else "网络不通或地址不对"
            err = LLMError(f"连不上模型服务（{kind}）：{_redact(str(reason), c.get('api_key') or '')}", "检查网络和 DZ_LLM_BASE_URL；比赛现场可能没网：调参/示波/阶跃测试不受影响，要 Agent 就开本地 Ollama", down=True)
            err.retry = True
            raise err from e
        self._account(usage, round((time.monotonic() - t0) * 1000))
        return m

    def _read_stream(self, r) -> tuple[dict, dict | None]:
        """SSE：content 逐段推 agent_delta；tool_calls 按 index 拼参数。"""
        text, calls, usage, shown = [], {}, None, 0
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            d = json.loads(data)
            usage = d.get("usage") or usage
            for ch in d.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    text.append(delta["content"])
                    raw_txt = "".join(text)
                    vis = THINK.sub("", raw_txt).lstrip()      # 思考段不推给界面（没闭合的 <think> 也藏住）
                    if len(vis) > shown and not "<think>".startswith(raw_txt.lstrip()):
                        self.emit({"type": "agent_delta", "text": vis[shown:]})
                        shown = len(vis)
                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    slot["id"] = tc.get("id") or slot["id"]
                    f = tc.get("function") or {}
                    slot["function"]["name"] += f.get("name") or ""
                    slot["function"]["arguments"] += f.get("arguments") or ""
        m = {"role": "assistant", "content": "".join(text)}
        if calls:
            m["tool_calls"] = [calls[i] for i in sorted(calls)]
        return m, usage

    def _account(self, usage: dict | None, elapsed_ms: int = 0) -> None:
        """累计 token；配置里填了每百万 token 单价（元）才算钱——价格各家常变，不内置。
        每次回复都发 agent_usage，带 usage={elapsed_ms[, tokens_in, tokens_out]}：服务没回 token 数时只有耗时。"""
        u = {"elapsed_ms": elapsed_ms}
        if usage:
            u |= {"tokens_in": int(usage.get("prompt_tokens") or 0), "tokens_out": int(usage.get("completion_tokens") or 0)}
        if not usage:
            self.emit({"type": "agent_usage", "model": self.name, **self.usage, "cost": None, "usage": u})
            return
        self.usage["prompt"] += int(usage.get("prompt_tokens") or 0)
        self.usage["completion"] += int(usage.get("completion_tokens") or 0)
        pi, po = self.cfg.get("price_in"), self.cfg.get("price_out")
        cost = (self.usage["prompt"] * float(pi) + self.usage["completion"] * float(po)) / 1e6 if pi not in (None, "") and po not in (None, "") else None
        self.emit({"type": "agent_usage", "model": self.name, **self.usage, "cost": cost, "usage": u})


class Failover:
    """云端为主、本地 Ollama 兜底：主模型连不上（不是 Key/余额这类错）→ 切本地并告诉界面；之后本次会话都用本地。"""

    def __init__(self, primary: OpenAICompat, local: OpenAICompat | None, emit: Callable[[dict], None]):
        self.primary, self.local, self.emit, self.active = primary, local, emit, primary

    @property
    def name(self) -> str:
        return self.active.name

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        try:
            return self.active.chat(messages, tools)
        except LLMError as e:
            if not e.down or self.local is None or self.active is self.local:
                raise
            self.active = self.local
            self.emit({"type": "agent_mode", "mode": "local", "name": self.local.name, "fallback": e.message})
            try:
                return self.local.chat(messages, tools)
            except LLMError as e2:
                raise LLMError(f"云端连不上，本地 {self.local.name} 也连不上：{e2.message}",
                               "开 Ollama 并拉好模型（设置里“检查 Ollama”）", down=True) from e2


def build(cfg: dict | None = None, emit: Callable[[dict], None] = lambda e: None):
    """按配置组装：有云端 Key → 云端（开了 failover 再挂本地兜底）；只配了 Ollama → 本地；都没有 → None。"""
    cfg = cfg or load_config()
    if cfg.get("provider") == "ollama":
        return OpenAICompat(cfg, on_event=emit)
    if not cfg.get("api_key"):
        return None
    local = OpenAICompat(local_config(cfg), on_event=emit, retries=0) if cfg.get("failover", True) else None
    return Failover(OpenAICompat(cfg, on_event=emit, retries=3), local, emit)
