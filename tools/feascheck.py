#!/usr/bin/env python3
"""randplant 可行性复核（#124）。给判卷侧（tools/tunegate.py，后端）用的 API，说明见 docs/dev/randplant-feasible.md。

    recheck(p)               → {"feasible": True|False|"unknown", "violation", "witness"}：独立细搜（换随机种子、加大预算）
    judge(p, verdict, met)   → "ok" | "false_pass" | "undecided"：卡上 verdict 对 randplant 标签 + 必要时 recheck
    summarize({seed: feasible}) → {"n", "unknown", "ratio", "unknown_seeds"}

CLI：python3 tools/feascheck.py [--seeds "3001-3012 4001-4040"] [--max-unknown 0.10]
     打印 unknown 个数和比例；比例 > 阈值时退出码 2（警告级，不是错误）。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import randplant  # noqa: E402

MAX_UNKNOWN = float(os.environ.get("FEAS_MAX_UNKNOWN", "0.10"))
DEFAULT_SEEDS = "3001-3012 4001-4040"


def recheck(p: dict, budget: int = 12000) -> dict:
    """与生成时的细搜独立：换一个随机种子、4 倍预算，在声明范围内对同一固件模型重搜。
    最好违约比 ≤1 → True（给 witness）；饱和可证明或 > UNSURE → False；否则 "unknown"。"""
    tg = randplant._targets(p)
    v, w = randplant.refine(p, tg, p["seed"] + 104729, budget=budget)
    if v <= 1.0:
        return {"feasible": True, "violation": v, "witness": w}
    proven = randplant.classify(p) == "saturation"
    return {"feasible": False if (proven or v > randplant.UNSURE) else "unknown", "violation": v, "witness": None}


def judge(p: dict, verdict: str, truth_meets_spec: bool) -> str:
    """卡上 verdict + 判卷在真值上复算的结果 → ok / false_pass / undecided。
    - 真值不满足题面却 pass → false_pass（不管标签）；
    - 标签 false 却 pass（且真值满足）→ 先 recheck：复核 true = 标签错、卡片对 → ok；复核 false → false_pass；
    - 标签 unknown 且 pass：真值满足 = 已有一组达标 → ok；
    - 标签 unknown 且非 pass：recheck，true → ok（由判卷按 feasible 规则另查质量），仍 unknown → undecided（单独计数、不进通过率）。"""
    f = p["feasible"]
    if verdict == "pass" and not truth_meets_spec:
        return "false_pass"
    if verdict == "pass":
        if f is False:
            return "ok" if recheck(p)["feasible"] is True else "false_pass"
        return "ok"
    if f == "unknown":
        return "undecided" if recheck(p)["feasible"] == "unknown" else "ok"
    return "ok"


def summarize(labels: dict) -> dict:
    unk = sorted(s for s, f in labels.items() if f == "unknown")
    n = len(labels)
    return {"n": n, "unknown": len(unk), "ratio": len(unk) / n if n else 0.0, "unknown_seeds": unk}


def _seeds(spec: str) -> list[int]:
    out = []
    for tok in spec.replace(",", " ").split():
        a, _, b = tok.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default=DEFAULT_SEEDS)
    ap.add_argument("--max-unknown", type=float, default=MAX_UNKNOWN)
    a = ap.parse_args(argv)
    labels = {s: randplant.gen(s)["feasible"] for s in _seeds(a.seeds)}
    st = summarize(labels)
    print(f"feasible：true {sum(f is True for f in labels.values())} / false {sum(f is False for f in labels.values())} / "
          f"unknown {st['unknown']}（{st['ratio']:.1%}，阈值 {a.max_unknown:.0%}）{st['unknown_seeds'] or ''}")
    return 2 if st["ratio"] > a.max_unknown else 0


if __name__ == "__main__":
    sys.exit(main())
