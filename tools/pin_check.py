#!/usr/bin/env python3
"""pin_check: board.yaml pin / resource consistency check (same rules as gen_board / alloc: boardlib.check_board,
plus boardlib.check_requires when --app is given). No new rules here.

Usage: pin_check.py <board.yaml> [--variant V] [--app app.yaml] [--json]
Exit codes (tools/tooljson.py): 0 no errors, 1 pin_conflict, 2 tool_bad_arg, 3 missing_dep, >=10 internal_error.
Default output is human-readable (rule messages come from boardlib); --json prints one envelope on stdout.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tooljson as T  # noqa: E402

TOOL, STAGE = "pin_check", "硬件"


def run(argv) -> tuple[int, dict]:
    ap = T.Parser(prog="pin_check.py")
    ap.add_argument("board", type=pathlib.Path)
    ap.add_argument("--variant", default=None)
    ap.add_argument("--app", type=pathlib.Path, default=None)
    ap.add_argument("--json", action="store_true")
    det = {}
    try:
        try:
            import yaml
            import boardlib
        except ImportError as e:
            return T.envelope(TOOL, STAGE, [T.error("missing_dep", module=e.name)])
        a = ap.parse_args(argv)
        det = {"board_abs": str(a.board.resolve())}
        for f in filter(None, (a.board, a.app)):
            if not f.is_file():
                raise T.BadArg(f"no such file: {T.rel(f)}")
        try:
            board = boardlib.load_board(a.board, a.variant)
            app = (yaml.safe_load(a.app.read_text(encoding="utf-8")) or {}) if a.app else None
        except (yaml.YAMLError, ValueError) as e:
            raise T.BadArg(f"{type(e).__name__}: {e}")
        rep = boardlib.check_board(board)
        if app is not None and not rep.errors:
            boardlib.check_requires(board, app, rep)
        rows = [["error", m] for m in rep.errors] + [["warning", m] for m in rep.warnings] + [["todo", m] for m in rep.todos]
        blocks = [T.kv({"board": board.get("name"), "family": (board.get("mcu") or {}).get("family"),
                        "errors": len(rep.errors), "warnings": len(rep.warnings), "todos": len(rep.todos)}),
                  T.table(["severity", "message"], rows)]
        errs = [T.error("pin_conflict", count=len(rep.errors))] if rep.errors else []
        return T.envelope(TOOL, STAGE, errs, blocks, det)
    except T.BadArg as e:
        return T.envelope(TOOL, STAGE, [T.error("tool_bad_arg", arg=str(e))], details=det)
    except Exception as e:  # noqa: BLE001
        return T.envelope(TOOL, STAGE, [T.error("internal_error", exc=f"{type(e).__name__}: {e}")], details=det)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    rc, env = run(argv)
    if "--json" in argv:
        T.emit(env)
        return rc
    for b in env["blocks"]:
        if b["type"] == "table":
            for sev, msg in b["rows"]:
                print(f"{sev.upper():8} {msg}")
    for e in env["errors"]:
        print(f"[{e['reason_code']}] {e['message_zh'] or ''} {e.get('details') or ''}".rstrip(), file=sys.stderr)
    print(f"pin_check: exit {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
