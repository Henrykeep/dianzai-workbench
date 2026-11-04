"""dzbench.mcp_server：用真正的 MCP 客户端（stdio）连服务，离线跑；驱动查询、编译报错解析、原因码。"""
import asyncio
import json
import os
import pathlib
import sys

from dzbench import buildparse, mcp_server

ROOT = pathlib.Path(__file__).resolve().parents[3]
EX = sorted(p.parent for p in ROOT.glob("examples/*/requirements.yaml") if (p.parent / "scheme.yaml").exists())[0]


def _mcp(calls):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        prm = StdioServerParameters(command=sys.executable, args=["-m", "dzbench.mcp_server"],
                                    cwd=str(ROOT / "app/sidecar"), env={**os.environ, "PYTHONPATH": str(ROOT / "app/sidecar")})
        async with stdio_client(prm) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            out = [json.loads((await s.call_tool(n, a)).content[0].text) for n, a in calls]
            return names, out
    return asyncio.run(go())


def test_stdio_client_end_to_end(tmp_path):
    names, out = _mcp([("req_check", {"requirements": str(EX / "requirements.yaml")}),
                       ("req_check", {"requirements": str(tmp_path / "nope.yaml")}),
                       ("pin_alloc", {"scheme": str(EX / "scheme.yaml"), "out_dir": str(tmp_path / "a"),
                                      "app": str(EX / "app.yaml")}),
                       ("driver_lookup", {"query": "AD9833"}),
                       ("nonexistent_tool", {})])
    assert {"req_check", "scheme_check", "project_check", "pin_alloc", "tunegate_score", "driver_lookup", "build", "reason_code"} <= set(names)
    assert out[0]["state"] == "ok", out[0]
    assert out[1]["reason_code"] == "tool_bad_arg" and out[1]["message_zh"]
    assert out[2]["state"] == "confirm_required" and out[2]["details"]["would_write"] and not (tmp_path / "a").exists()
    assert out[3]["state"] == "ok" and out[3]["drivers"][0]["part"] == "AD9833"
    assert out[4]["reason_code"] == "tool_bad_arg"


def test_pin_alloc_confirm_writes(tmp_path):
    r = asyncio.run(mcp_server.call("pin_alloc", {"scheme": str(EX / "scheme.yaml"), "out_dir": str(tmp_path / "a"),
                                                  "app": str(EX / "app.yaml"), "confirm": True}))
    assert r["state"] == "ok" and (tmp_path / "a" / "board.yaml").exists()


def test_driver_lookup_fields_and_config(tmp_path, monkeypatch):
    r = mcp_server.driver_lookup(category="ADC")
    assert r["count"] > 1
    d = r["drivers"][0]
    assert {"path", "license", "style", "port_needs", "compiled"} <= set(d) and d["port_needs"]["hooks"]
    assert mcp_server.driver_lookup(query="no-such-part-xyz")["reason_code"] == "driver_not_found"
    cat = tmp_path / "c.yaml"
    cat.write_text("entries:\n- {part: FOO1, category: X, path: p, license: MIT, hooks: [spi], backbone: libdriver, status: s, compiled: true}\n")
    monkeypatch.setenv("DZBENCH_DRIVER_CATALOG", str(cat))
    assert mcp_server.driver_lookup(query="foo1")["drivers"][0]["compiled"] is True
    monkeypatch.setenv("DZBENCH_DRIVER_CATALOG", str(tmp_path / "missing.yaml"))
    assert mcp_server.driver_lookup(query="x")["reason_code"] == "driver_catalog_missing"


def test_buildparse_gcc_keil_ti():
    log = "\n".join([
        "src/main.c:12:5: error: 'foo' undeclared (first use in this function)",
        "src/pid.c:40:1: warning: unused variable 'k' [-Wunused-variable]",
        "Core/Src/app.c(88): error:  #20: identifier \"bar\" is undefined",
        '"../src/adc.c", line 7: error #20: identifier "x" is undefined',
        "/usr/bin/ld: main.o: in function `main': undefined reference to `baz'",
        "*** [.pio/build/x/firmware.elf] Error 1"])
    r = buildparse.parse(log)
    files = [e["file"] for e in r["errors"]]
    assert files[:3] == ["src/main.c", "Core/Src/app.c", "../src/adc.c"] and r["errors"][0]["line"] == 12 and r["errors"][0]["col"] == 5
    assert r["n_warnings"] == 1 and any("undefined reference" in e["message"] for e in r["errors"])


def test_build_log_and_missing_project(tmp_path):
    lg = tmp_path / "b.log"
    lg.write_text("a.c:3:1: error: expected ';'\n")
    r = asyncio.run(mcp_server.call("build", {"log_path": str(lg)}))
    assert r["reason_code"] == "build_failed" and r["errors"][0]["line"] == 3
    assert asyncio.run(mcp_server.call("build", {"project_dir": str(tmp_path)}))["reason_code"] == "tool_bad_arg"


def test_every_failure_code_registered():
    from dzbench.agent.reason_codes import table
    t = table()
    for c in list(mcp_server.EXIT_RC.values()) + ["tool_error", "build_failed", "missing_platformio", "driver_not_found",
                                                  "driver_catalog_missing", "tool_timeout", "confirm_required"]:
        assert t[c]["zh"] and t[c].get("fix_action"), c
