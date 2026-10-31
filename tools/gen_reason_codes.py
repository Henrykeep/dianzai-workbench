#!/usr/bin/env python3
"""生成 docs/dev/reason_codes.json（{code: {zh, kind}}）——来源是后端 dzbench.agent.reason_codes。--check：文件不是最新就失败。"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "sidecar"))
from dzbench.agent.reason_codes import table  # noqa: E402

OUT = ROOT / "docs/dev/reason_codes.json"


def render() -> str:
    return json.dumps(table(), ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    if "--check" in sys.argv:
        ok = OUT.exists() and OUT.read_text("utf-8") == render()
        print("reason_codes.json：" + ("最新" if ok else "过期，跑 tools/gen_reason_codes.py 重新生成"))
        sys.exit(0 if ok else 1)
    OUT.write_text(render(), "utf-8")
    print(f"写入 {OUT.relative_to(ROOT)}")
