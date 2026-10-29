#!/usr/bin/env python3
"""对比两次参数回读（last-good 对比）：params.txt（侧车 Session.export_readback / op params_readback）或参数快照 .json。

  python3 tools/params_diff.py last_good.txt now.txt [--tol 1e-6]

输出：schema / 固件版本是否相同，改了的（旧 → 新）、只在一边有的。完全一致退出 0，有差异退出 1，文件读不了退出 2。
用法场景：赛前/换电池/重新烧录后回读一次，和存档的 last-good 比，确认板上参数就是调好的那组（照 DS 的 P 命令 + p_before.txt）。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys


def load(path: str | pathlib.Path) -> tuple[dict, dict]:
    """返回 (meta, values)。"""
    p = pathlib.Path(path)
    t = p.read_text(encoding="utf-8")
    if p.suffix == ".json":
        j = json.loads(t)
        return {"time": j.get("time", ""), "note": j.get("note", "")}, {k: float(v) for k, v in j["values"].items()}
    meta, vals = {}, {}
    for ln in t.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("#"):
            if "=" in ln:
                k, v = ln[1:].split("=", 1)
                meta[k.strip()] = v.strip()
            continue
        if "=" not in ln:
            raise ValueError(f"{p}: 看不懂这一行：{ln}")
        k, v = ln.split("=", 1)
        vals[k.strip()] = float(v)
    return meta, vals


def diff(a: tuple[dict, dict], b: tuple[dict, dict], tol: float = 1e-6) -> dict:
    (ma, va), (mb, vb) = a, b
    same = lambda x, y: math.isclose(x, y, rel_tol=tol, abs_tol=tol)   # noqa: E731
    return {
        "meta": {k: (ma.get(k), mb.get(k)) for k in ("schema_hash", "fw_rev", "board_uid") if ma.get(k) and mb.get(k) and ma[k] != mb[k]},   # 一边没有（快照 json）不算差异
        "changed": [(k, va[k], vb[k]) for k in va if k in vb and not same(va[k], vb[k])],
        "only_a": [k for k in va if k not in vb], "only_b": [k for k in vb if k not in va],
    }


def render(d: dict, na: str, nb: str) -> str:
    L = [f"对比 {na} → {nb}"]
    for k, (x, y) in d["meta"].items():
        L.append(f"  ! {k} 不同：{x} → {y}" + ("（参数表变了，序号可能不对应）" if k == "schema_hash" else ""))
    for k, x, y in d["changed"]:
        L.append(f"  ~ {k}: {x:.9g} → {y:.9g}")
    L += [f"  - {k}（只在 {na}）" for k in d["only_a"]] + [f"  + {k}（只在 {nb}）" for k in d["only_b"]]
    n = len(d["changed"]) + len(d["only_a"]) + len(d["only_b"])
    L.append("  ✓ 参数完全一致" if not n and not d["meta"] else f"  共 {n} 处参数差异")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a"); ap.add_argument("b")
    ap.add_argument("--tol", type=float, default=1e-6, help="相对/绝对容差（f32 回读的末位误差）")
    x = ap.parse_args(argv)
    try:
        d = diff(load(x.a), load(x.b), x.tol)
    except (OSError, ValueError, KeyError) as e:
        print(f"params_diff: {e}", file=sys.stderr); return 2
    print(render(d, pathlib.Path(x.a).name, pathlib.Path(x.b).name))
    return 0 if not (d["changed"] or d["only_a"] or d["only_b"] or d["meta"]) else 1


if __name__ == "__main__":
    sys.exit(main())
