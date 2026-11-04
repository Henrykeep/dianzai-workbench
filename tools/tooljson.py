#!/usr/bin/env python3
"""Unified --json envelope + exit codes for firmware-side tools (gen_link / pin_check / selfcheck / tunegate).

Matches /workspace/feedback/backend/tool-api-draft.md section 4 (tool_run reply):
  stdout = exactly one JSON object {tool, stage, state, exit_code, blocks, errors, details}; human text -> stderr.
  state  = ok | error | confirm_required
  errors = [{reason_code, fix_action, message_zh}]; message_zh is looked up in docs/dev/reason_codes.json
           (the single source of Chinese text; null when the code is not registered there yet).
Exit codes: 0 ok, 1 not up to spec, 2 bad args, 3 missing dependency, 4 no board, 5 needs confirmation, >=10 internal.
Determinism: sort_keys, ASCII-only, no timestamps; absolute paths / timings only under `details`.
Pure stdlib; no OS-specific paths.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REASON_FILE = ROOT / "docs" / "dev" / "reason_codes.json"

OK, NOT_MET, BAD_ARG, MISSING_DEP, NO_BOARD, CONFIRM, INTERNAL = 0, 1, 2, 3, 4, 5, 10
# reason_code -> (exit code, fix_action). Every non-zero exit must come from one of these.
CODES = {
    "tool_bad_arg": (BAD_ARG, "fix_params"),
    "missing_dep": (MISSING_DEP, "install_dep"),
    "no_board": (NO_BOARD, "connect_board"),
    "confirm_required": (CONFIRM, "confirm"),
    "internal_error": (INTERNAL, "report_bug"),
    "link_spec_invalid": (NOT_MET, "goto:固件"),
    "pin_conflict": (NOT_MET, "goto:硬件"),
    "selfcheck_failed": (NOT_MET, "reinstall"),
    "selfcheck_incomplete": (MISSING_DEP, "install_dep"),
    "data_missing": (MISSING_DEP, "reinstall"),
    "tune_fake_pass": (NOT_MET, "goto:调参"),
    "tune_standin": (NOT_MET, "none"),
}
STAGES = ("读题", "方案", "硬件", "固件", "调试", "调参", "报告")


def reason_zh(code: str):
    try:
        e = json.loads(REASON_FILE.read_text(encoding="utf-8")).get(code)
    except (OSError, ValueError):
        return None
    return (e.get("message_zh") or e.get("zh")) if isinstance(e, dict) else None


def error(code: str, **details) -> dict:
    rc, fix = CODES[code]
    e = {"reason_code": code, "fix_action": fix, "message_zh": reason_zh(code)}
    if details:
        e["details"] = details
    return e


def envelope(tool: str, stage: str, errors=(), blocks=(), details=None, preview=None) -> tuple[int, dict]:
    """Exit code = that of the first error (errors ordered by priority by the caller)."""
    assert stage in STAGES, stage
    errors = list(errors)
    rc = CODES[errors[0]["reason_code"]][0] if errors else OK
    state = "ok" if rc == OK else ("confirm_required" if rc == CONFIRM else "error")
    env = {"tool": tool, "stage": stage, "state": state, "exit_code": rc, "blocks": list(blocks),
           "errors": errors, "details": details or {}}
    if preview is not None:
        env["preview"] = preview
    return rc, env


def dumps(env: dict) -> str:
    return json.dumps(env, ensure_ascii=True, sort_keys=True, indent=1, default=str) + "\n"


def emit(env: dict) -> None:
    out = sys.stdout
    try:
        out.reconfigure(newline="\n")  # byte-identical on Windows (no CRLF)
    except (AttributeError, ValueError):
        pass
    out.write(dumps(env))
    out.flush()


def rel(p) -> str:
    """Repo-relative POSIX path when inside the repo, else just the file name (abs paths go to details only)."""
    p = pathlib.Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.name


class BadArg(Exception):
    pass


class Parser(argparse.ArgumentParser):
    """argparse that raises BadArg instead of exit(2) so --json can still print an envelope."""
    def error(self, message):
        raise BadArg(message)


def kv(items: dict) -> dict:
    return {"type": "kv", "items": items}


def table(columns, rows) -> dict:
    return {"type": "table", "columns": list(columns), "rows": [list(r) for r in rows]}
