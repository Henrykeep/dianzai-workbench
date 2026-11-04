"""芯台 MCP 服务：只放现成 MCP 服务（embedded-debugger-mcp / mcp-hardware-tools / mcp-stm32cubeide-server /
serial-mcp-server / sigrok-mcp-server，见 tools/mcp/servers.json）没有的工具——需求校验、方案/工程校验、引脚分配、
调参评分、器件驱动查询、编译（PlatformIO + 结构化报错）。

骨架照搬 mcp-stm32cubeide-server server.py（MIT，github.com/Helistana/mcp-stm32cubeide-server@860d90b）的
Server + list_tools/call_tool 写法；工具本体全部调用仓库已有 CLI（tools/*.py），这里只是薄包装。
每个工具返回一个 JSON：成功 {state: ok, ...}；失败 {state: error|not_met|confirm_required, reason_code, message_zh, fix_action, details}。
中文原因只从 dzbench.agent.reason_codes 表取。改文件的工具（pin_alloc）要 confirm=true，否则返回 confirm_required + 预览。

运行：python -m dzbench.mcp_server            （stdio）
      python -m dzbench.mcp_server --http 8765  （streamable HTTP，路径 /mcp）
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import sys
import tempfile

import yaml

from . import buildparse
from .agent.reason_codes import table as rc_table

ROOT = pathlib.Path(__file__).resolve().parents[3]
PY = sys.executable
EXIT_RC = {1: "tool_not_met", 2: "tool_bad_arg", 3: "tool_missing_dep", 4: "no_board_tool", 5: "confirm_required"}


def driver_catalog_path() -> pathlib.Path:
    """器件驱动总表：环境变量 DZBENCH_DRIVER_CATALOG > 仓库内 tools/catalog/drivers.yaml。"""
    return pathlib.Path(os.environ.get("DZBENCH_DRIVER_CATALOG") or ROOT / "tools/catalog/drivers.yaml")


def _p(s: str) -> pathlib.Path:
    p = pathlib.Path(s).expanduser()
    return p if p.is_absolute() else ROOT / p


def fail(code: str, details=None, state: str = "error") -> dict:
    r = rc_table().get(code, {})
    return {"state": state, "reason_code": code, "message_zh": r.get("zh", code), "fix_action": r.get("fix_action"),
            "details": details}


async def _run(cmd: list[str], timeout: int = 300, cwd: pathlib.Path = ROOT) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        await proc.wait()
        raise
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def _cli(cmd: list[str], timeout: int = 300, **extra) -> dict:
    try:
        rc, out, err = await _run(cmd, timeout)
    except asyncio.TimeoutError:
        return fail("tool_timeout", {"cmd": cmd[1:]})
    tail = {"stdout": out[-4000:], "stderr": err[-2000:], "exit_code": rc}
    if rc == 0:
        return {"state": "ok", **extra, "output": out[-4000:]}
    code = EXIT_RC.get(rc, "tool_error")
    return fail(code, tail, state="not_met" if code == "tool_not_met" else "error")


def _need(path: str, what: str) -> dict | None:
    return None if path and _p(path).exists() else fail("tool_bad_arg", {"missing": what, "path": path})


# ── 工具实现 ────────────────────────────────────────────────────────────────

async def req_check(requirements: str, strict: bool = False) -> dict:
    return _need(requirements, "requirements") or await _cli(
        [PY, "tools/req.py", "check", str(_p(requirements))] + (["--strict"] if strict else []))


async def scheme_check(requirements: str, scheme: str) -> dict:
    return (_need(requirements, "requirements") or _need(scheme, "scheme")
            or await _cli([PY, "tools/scheme.py", str(_p(requirements)), "--scheme", str(_p(scheme))]))


async def project_check(project: str) -> dict:
    return _need(project, "project") or await _cli([PY, "tools/gen_project.py", str(_p(project)), "--check"])


async def pin_alloc(scheme: str, out_dir: str, app: str = "", fixed: str = "", confirm: bool = False) -> dict:
    bad = _need(scheme, "scheme") or (app and _need(app, "app")) or (fixed and _need(fixed, "fixed"))
    if bad:
        return bad
    extra = (["--app", str(_p(app))] if app else []) + (["--fixed", str(_p(fixed))] if fixed else [])
    if not confirm:      # 预览：分配到临时目录，给出会写哪些文件
        with tempfile.TemporaryDirectory() as t:
            r = await _cli([PY, "tools/alloc.py", str(_p(scheme)), "-o", t] + extra)
            files = sorted(str(f.relative_to(t)) for f in pathlib.Path(t).rglob("*") if f.is_file())
            board = (pathlib.Path(t) / "board.yaml").read_text("utf-8") if (pathlib.Path(t) / "board.yaml").exists() else None
        if r["state"] != "ok":
            return r
        return fail("confirm_required", {"would_write": [str(_p(out_dir) / f) for f in files], "board_yaml": board},
                    state="confirm_required")
    return await _cli([PY, "tools/alloc.py", str(_p(scheme)), "-o", str(_p(out_dir))] + extra, out_dir=str(_p(out_dir)))


async def tunegate_score(seeds: str = "", n: int = 1, kind: str = "") -> dict:
    with tempfile.TemporaryDirectory() as t:
        js = pathlib.Path(t) / "tg.json"
        cmd = [PY, "tools/tunegate.py", "--n", str(n), "--json", str(js)] + (["--seeds", seeds] if seeds else []) + (["--kind", kind] if kind else [])
        r = await _cli(cmd, timeout=1800)
        if js.exists():
            r["score"] = json.loads(js.read_text("utf-8"))
        return r


def driver_lookup(query: str = "", category: str = "", limit: int = 10) -> dict:
    p = driver_catalog_path()
    if not p.exists():
        return fail("driver_catalog_missing", {"path": str(p)})
    cat = yaml.safe_load(p.read_text("utf-8")) or {}
    q, c = query.strip().lower(), category.strip().lower()
    if not q and not c:
        return fail("tool_bad_arg", {"missing": "query 或 category"})
    hits = []
    for e in cat.get("entries", []):
        name, ec = str(e.get("part", "")).lower(), str(e.get("category", "")).lower()
        if (q and (q == name or q in name or name in q.split())) or (c and c in ec) or (q and not c and q in ec):
            hooks = e.get("hooks") or []
            hits.append({"part": e.get("part"), "category": e.get("category"), "path": e.get("path"), "repo": e.get("repo"),
                         "commit": e.get("commit"), "license": e.get("license"), "style": e.get("backbone"),
                         "port_needs": {"hooks": hooks, "note": e.get("status")}, "compiled": bool(e.get("compiled", False))})
    hits.sort(key=lambda h: (str(h["part"]).lower() != q, str(h["part"])))
    if not hits:
        return fail("driver_not_found", {"query": query, "category": category, "catalog": str(p)}, state="not_met")
    return {"state": "ok", "catalog": str(p), "count": len(hits), "drivers": hits[:max(1, limit)]}


async def build(project_dir: str = "", env: str = "", log_path: str = "", timeout_s: int = 900) -> dict:
    """PlatformIO 编译（pio run）；或给 log_path 只解析已有日志（Keil UV4 -b / CCS / make 的输出同一个解析器）。"""
    if log_path:
        if not _p(log_path).exists():
            return fail("tool_bad_arg", {"missing": "log_path", "path": log_path})
        res = buildparse.parse(_p(log_path).read_text("utf-8", "replace"))
        return ({"state": "ok", **res} if res["n_errors"] == 0 else fail("build_failed", res, state="not_met") | res)
    if not project_dir or not (_p(project_dir) / "platformio.ini").exists():
        return fail("tool_bad_arg", {"missing": "platformio.ini", "project_dir": project_dir})
    pio = shutil.which("pio") or shutil.which("platformio")
    if not pio:
        return fail("missing_platformio")
    try:
        rc, out, err = await _run([pio, "run", "-d", str(_p(project_dir))] + (["-e", env] if env else []), timeout_s)
    except asyncio.TimeoutError:
        return fail("tool_timeout", {"project_dir": project_dir})
    res = buildparse.parse(out + "\n" + err)
    if rc == 0:
        return {"state": "ok", **res}
    return fail("build_failed", {"tail": (out + err)[-3000:]}, state="not_met") | res


def reason_code(code: str) -> dict:
    r = rc_table().get(code)
    return {"state": "ok", "reason_code": code, "message_zh": r["zh"], "kind": r["kind"], "fix_action": r.get("fix_action")} if r \
        else fail("tool_bad_arg", {"unknown_reason_code": code})


# ── 工具声明（JSON Schema）────────────────────────────────────────────────

S, B, I = {"type": "string"}, {"type": "boolean"}, {"type": "integer"}
TOOLS: list[dict] = [
    {"name": "req_check", "fn": req_check, "description": "校验 requirements.yaml（schema/requirements.schema.json + 评分项/指标/子系统一致性）",
     "schema": {"requirements": S, "strict": B}, "required": ["requirements"]},
    {"name": "scheme_check", "fn": scheme_check, "description": "核对方案 scheme.yaml：选的器件真能提供 requirements 里要的能力、没被禁用、串口够用",
     "schema": {"requirements": S, "scheme": S}, "required": ["requirements", "scheme"]},
    {"name": "project_check", "fn": project_check, "description": "校验 project.yaml（子系统/共享状态/参数/测试项）能否生成",
     "schema": {"project": S}, "required": ["project"]},
    {"name": "pin_alloc", "fn": pin_alloc, "description": "按 scheme.yaml 自动分配引脚/定时器/DMA，出 board.yaml 草稿；confirm=false 只预览",
     "schema": {"scheme": S, "out_dir": S, "app": S, "fixed": S, "confirm": B}, "required": ["scheme", "out_dir"]},
    {"name": "tunegate_score", "fn": tunegate_score, "description": "调参评分：在随机被控对象上跑自动整定并判卷，返回通过率和假达标",
     "schema": {"seeds": S, "n": I, "kind": S}, "required": []},
    {"name": "driver_lookup", "fn": driver_lookup, "description": "按器件型号或类别查现成开源驱动：路径、许可、接口风格(libdriver/adi-no-os)、要移植的钩子、是否已编译",
     "schema": {"query": S, "category": S, "limit": I}, "required": []},
    {"name": "build", "fn": build, "description": "PlatformIO 编译并把 gcc 格式报错解析成 file/line/message；或解析 Keil/CCS/make 日志（log_path）",
     "schema": {"project_dir": S, "env": S, "log_path": S, "timeout_s": I}, "required": []},
    {"name": "reason_code", "fn": reason_code, "description": "查原因码的中文说明和修复动作", "schema": {"code": S}, "required": ["code"]},
]


async def call(name: str, args: dict) -> dict:
    t = next((t for t in TOOLS if t["name"] == name), None)
    if not t:
        return fail("tool_bad_arg", {"unknown_tool": name})
    args = {k: v for k, v in (args or {}).items() if k in t["schema"]}
    if any(k not in args for k in t["required"]):
        return fail("tool_bad_arg", {"required": t["required"]})
    try:
        r = t["fn"](**args)
        return await r if asyncio.iscoroutine(r) else r
    except Exception as e:  # noqa: BLE001  工具内部错：不让服务崩，给原因码
        return fail("tool_error", {"exc": f"{type(e).__name__}: {e}"})


def build_server():
    from mcp.server import Server
    from mcp.types import TextContent, Tool
    server = Server("xintai-workbench")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(name=t["name"], description=t["description"],
                     inputSchema={"type": "object", "properties": t["schema"], "required": t["required"]}) for t in TOOLS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(await call(name, arguments), ensure_ascii=False))]

    return server


async def _stdio():
    from mcp.server.stdio import stdio_server
    server = build_server()
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


def http_app():
    import contextlib

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount
    mgr = StreamableHTTPSessionManager(app=build_server(), json_response=True, stateless=True)

    async def handle(scope, receive, send):
        await mgr.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def life(_app):
        async with mgr.run():
            yield
    return Starlette(routes=[Mount("/mcp", app=handle)], lifespan=life)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--http" in argv:
        import uvicorn
        port = int(argv[argv.index("--http") + 1])
        uvicorn.run(http_app(), host="127.0.0.1", port=port, log_level="warning")
    else:
        asyncio.run(_stdio())
    return 0


if __name__ == "__main__":
    sys.exit(main())
