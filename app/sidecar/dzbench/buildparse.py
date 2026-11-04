"""编译输出 → 结构化错误（file/line/col/severity/message），给 Agent「编译→改→再编」闭环用。

认三种格式：gcc/clang（PlatformIO、make、arm-none-eabi-gcc、TI armcl 新版）、Keil armcc/armclang（UV4 -b 日志）、
TI CCS 旧版 armcl（"file", line N: error #xx: msg）。认不出的行不丢，计入 unparsed。
"""
from __future__ import annotations

import re

GCC = re.compile(r"^(?P<file>[^:\n]+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>fatal error|error|warning|note):\s*(?P<msg>.+)$")
KEIL = re.compile(r"^(?P<file>[^()\n]+?)\((?P<line>\d+)\):\s*(?P<sev>error|warning|note)(?::\s*#?\s*\w*:?)?\s*(?P<msg>.*)$", re.I)
TI = re.compile(r'^"(?P<file>[^"]+)",\s*line\s*(?P<line>\d+):\s*(?P<sev>fatal error|error|warning|remark)\s*(?:#\w+-?\w*)?:?\s*(?P<msg>.*)$', re.I)
LD = re.compile(r"(?P<msg>undefined reference to .+|region .+ overflowed by \d+ bytes|multiple definition of .+)$")


def parse(text: str) -> dict:
    items, unparsed = [], 0
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        m = GCC.match(ln) or TI.match(ln) or KEIL.match(ln)
        if m:
            sev = m["sev"].lower().replace("fatal error", "error").replace("remark", "note")
            items.append({"file": m["file"].strip(), "line": int(m["line"]),
                          "col": int(m["col"]) if "col" in m.groupdict() and m["col"] else None,
                          "severity": sev, "message": m["msg"].strip()})
            continue
        lm = LD.search(ln)
        if lm and ("ld" in ln or "undefined reference" in ln or "region" in ln):
            items.append({"file": None, "line": None, "col": None, "severity": "error", "message": lm["msg"].strip()})
            continue
        if re.search(r"\berror\b", ln, re.I):
            unparsed += 1
    errs = [i for i in items if i["severity"] == "error"]
    return {"errors": errs, "warnings": [i for i in items if i["severity"] == "warning"],
            "n_errors": len(errs), "n_warnings": sum(i["severity"] == "warning" for i in items), "unparsed_error_lines": unparsed}
