"""Keil MDK 无界面编译：`UV4 -b proj.uvprojx -t target -j0 -o build.log`，解析日志为结构化 JSON。

思路参考 embeddedskills（MIT）的 keil 技能；解析器自写。UV4 退出码：0 无错无警告，1 有警告，2+ 有错误（Keil 文档）。
⚠ 未在装了 Keil 的 Windows 上实测，只用日志样本单测。
"""
from __future__ import annotations

import pathlib
import re
import subprocess

DIAG = re.compile(r"^(?P<file>[^\s(][^(]*?)\((?P<line>\d+)\):\s*(?P<sev>error|warning|note):\s*(?:#?(?P<code>[\w-]+):\s*)?(?P<msg>.*)$", re.I)
CLANG = re.compile(r"^(?P<file>[^:\s][^:]*?):(?P<line>\d+):(?P<col>\d+):\s*(?P<sev>error|warning|note):\s*(?P<msg>.*?)(?:\s*\[(?P<code>[^\]]+)\])?$", re.I)
SUMMARY = re.compile(r'"(?P<img>[^"]+)"\s*-\s*(?P<e>\d+)\s+Error\(s\),\s*(?P<w>\d+)\s+Warning\(s\)', re.I)
SIZE = re.compile(r"Program Size:\s*Code=(?P<code>\d+)\s+RO-data=(?P<ro>\d+)\s+RW-data=(?P<rw>\d+)\s+ZI-data=(?P<zi>\d+)", re.I)


def parse_log(text: str) -> dict:
    diags, out = [], {"ok": None, "errors": 0, "warnings": 0, "image": None, "size": None}
    for ln in text.splitlines():
        ln = ln.strip()
        m = CLANG.match(ln) or DIAG.match(ln)
        if m:
            d = m.groupdict()
            diags.append({"file": d["file"].strip(), "line": int(d["line"]), "severity": d["sev"].lower(),
                          "code": d.get("code"), "message": d["msg"].strip()})
            continue
        if m := SUMMARY.search(ln):
            out |= {"image": m["img"], "errors": int(m["e"]), "warnings": int(m["w"])}
        if m := SIZE.search(ln):
            out["size"] = {k: int(v) for k, v in m.groupdict().items()}
            out["size"]["flash"] = out["size"]["code"] + out["size"]["ro"] + out["size"]["rw"]
            out["size"]["ram"] = out["size"]["rw"] + out["size"]["zi"]
    if out["image"] is None:          # 没有汇总行：按诊断计数
        out["errors"] = sum(d["severity"] == "error" for d in diags)
        out["warnings"] = sum(d["severity"] == "warning" for d in diags)
    out["ok"] = out["errors"] == 0 and ("Error(s)" in text or out["size"] is not None or not diags)
    out["diagnostics"] = diags[:200]
    return out


def build(uv4: str, project: str, target: str | None = None, timeout: int = 600, runner=subprocess.run) -> dict:
    proj = pathlib.Path(project)
    log = proj.with_suffix(".dzbench_build.log")
    cmd = [uv4, "-b", str(proj), "-j0", "-o", str(log)] + (["-t", target] if target else [])
    r = runner(cmd, capture_output=True, text=True, timeout=timeout)
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else (r.stdout or "")
    res = parse_log(text) | {"exit_code": r.returncode, "cmd": cmd}
    if r.returncode >= 2:
        res["ok"] = False
    return res
