#!/usr/bin/env python3
"""一键出报告用的测试数据表 + 阶跃曲线（电赛设计报告"测试方案与测试结果"一节，评分 20 分里的一块）。

输入：工作台录下的 .dzlog（按 schema 解码）或导出的 .csv（第一列 t_s，其余列名可带 [单位]）。
     每个文件 = 一次测试（题目一般要求同一项重复测几次，H 题还要求"完整记录每次测试"）。
输出（-o 目录）：
  results.md   参数表 + 每次测试的指标表 + 汇总（平均 / 最差）+ 是否满足要求 + 曲线引用，直接贴进报告
  results.csv  同一张表，Excel / Word 里粘贴用
  step.svg     所有次叠在一起的阶跃曲线（阶跃起点对齐、虚线是设定值、灰带是 ±误差带）
  run_<n>.svg  每次单独一张
指标算法和工作台调参用的是同一个函数（app/sidecar/dzbench/agent/tuning.py step_metrics），报告和现场看到的数一致。
SVG 不依赖 matplotlib（赛场电脑不一定能 pip），Word 2016+ / WPS 可直接插入。

不编数据：
  --source 必填（board = 实物，sim = 仿真）。仿真数据在表头和每行都标"仿真"，不能当实测交。
  --params 参数快照（工作台"存快照"的 json）；没给就写"（未提供）"，不猜。
  --req overshoot<=10 / settling<=1.5 / sse<=2 / rise<=0.5 / osc<=1：按题目要求判"满足/不满足"，不给就不判。

例：python3 tools/report.py runs/*.csv --y y --sp sp --source board \\
        --params ~/.dzbench/snapshots/XXXX/定稿.json --req overshoot<=10 --req settling<=2 \\
        --title "基本要求(2) 定点" -o report/basic2
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "sidecar"))
from dzbench.agent.tuning import step_metrics  # noqa: E402  与工作台同一套指标

REQ_KEYS = {  # 名字 → (StepMetrics 字段, 表头, 单位, 取绝对值)
    "overshoot": ("overshoot_pct", "超调量", "%", False),
    "settling": ("settling_s", "调节时间", "s", False),
    "sse": ("sse_pct", "稳态误差", "%", True),
    "rise": ("rise_s", "上升时间", "s", False),
    "osc": ("oscillations", "振荡次数", "次", False),
}
ORDER = ["rise", "overshoot", "settling", "sse", "osc"]


class ReportError(Exception):
    pass


def _strip_unit(name: str) -> str:
    return re.sub(r"\[.*\]$", "", name).strip()


def load_run(path: pathlib.Path) -> tuple[dict[str, list[float]], str]:
    """返回 (列名→数值列表, 来源说明)。.dzlog 先按 schema 解码成 CSV。"""
    note = ""
    if path.suffix == ".dzlog":
        from dzbench.export import ExportError, dzlog_to_csv
        from dzbench.logfile import read_log
        hdr, _ = read_log(path)
        note = str(hdr.get("port", ""))
        tmp = pathlib.Path(tempfile.mkdtemp()) / (path.stem + ".csv")
        try:
            dzlog_to_csv(path, tmp)
        except ExportError as e:
            raise ReportError(f"{path.name}: {e.message}；{e.fix}") from None
        path = tmp
    cols: dict[str, list[float]] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        r = csv.reader(fh)
        head = [_strip_unit(h) for h in next(r)]
        for h in head:
            cols[h] = []
        for row in r:
            for h, v in zip(head, row):
                try:
                    cols[h].append(float(v))
                except ValueError:
                    cols[h].append(math.nan)
    if "t_s" not in cols and "time" in cols:
        cols["t_s"] = cols["time"]
    if "t_s" not in cols:
        raise ReportError(f"{path.name}: 没有 t_s / time 列")
    return cols, note


def parse_req(items: list[str]) -> list[tuple[str, str, float]]:
    out = []
    for it in items or []:
        m = re.fullmatch(r"\s*(\w+)\s*(<=|>=|<|>)\s*([-+\d.eE]+)\s*", it)
        if not m or m.group(1) not in REQ_KEYS:
            raise ReportError(f"--req {it!r} 看不懂；写成 overshoot<=10 / settling<=1.5 / sse<=2 / rise<=0.5 / osc<=1")
        out.append((m.group(1), m.group(2), float(m.group(3))))
    return out


def judge(val, op, lim) -> bool | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return False   # 没进误差带（调节时间=None）按不满足算
    return {"<=": val <= lim, ">=": val >= lim, "<": val < lim, ">": val > lim}[op]


def metric_val(m, key):
    f, _, _, ab = REQ_KEYS[key]
    v = getattr(m, f)
    return abs(v) if (ab and v is not None) else v


def fmt(v, unit=""):
    if v is None:
        return "未进带"
    if isinstance(v, int):
        return str(v)
    return f"{v:.3g}" if abs(v) < 100 else f"{v:.0f}"


# ---------------- SVG ----------------
def _nice(lo, hi, n=5):
    span = hi - lo if hi > lo else 1.0
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    a = math.floor(lo / step) * step
    ticks, v = [], a
    while v <= hi + step * 1e-6:
        ticks.append(round(v, 10))
        v += step
    return ticks


COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#17becf", "#7f7f7f"]


def svg_plot(series, sp_line, band, title, xlabel, ylabel, w=720, h=360) -> str:
    """series: [(label, xs, ys)]；sp_line: (xs, ys) 或 None；band: (lo, hi) 或 None。"""
    xs_all = [x for _, xs, _ in series for x in xs] + (sp_line[0] if sp_line else [])
    ys_all = [y for _, _, ys in series for y in ys if not math.isnan(y)] + (sp_line[1] if sp_line else [])
    if band:
        ys_all += list(band)
    x0, x1 = min(xs_all), max(xs_all)
    y0, y1 = min(ys_all), max(ys_all)
    pad = (y1 - y0) * 0.08 or 1.0
    y0, y1 = y0 - pad, y1 + pad
    xt, yt = _nice(x0, x1), _nice(y0, y1)
    x0, x1 = min(x0, xt[0]), max(x1, xt[-1])
    y0, y1 = min(y0, yt[0]), max(y1, yt[-1])
    L, R, T, B = 64, 104, 34, 46
    px = lambda x: L + (x - x0) / (x1 - x0 or 1) * (w - L - R)
    py = lambda y: h - B - (y - y0) / (y1 - y0 or 1) * (h - T - B)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
         f'font-family="SimSun, Songti SC, Noto Serif CJK SC, serif" font-size="12">',
         f'<rect width="{w}" height="{h}" fill="white"/>',
         f'<text x="{w/2}" y="20" text-anchor="middle" font-size="14">{_esc(title)}</text>']
    if band:
        o.append(f'<rect x="{L}" y="{py(band[1]):.1f}" width="{w-L-R}" height="{py(band[0])-py(band[1]):.1f}" fill="#000" fill-opacity="0.07"/>')
    for t in xt:
        o.append(f'<line x1="{px(t):.1f}" y1="{T}" x2="{px(t):.1f}" y2="{h-B}" stroke="#ddd"/>'
                 f'<text x="{px(t):.1f}" y="{h-B+16}" text-anchor="middle">{t:g}</text>')
    for t in yt:
        o.append(f'<line x1="{L}" y1="{py(t):.1f}" x2="{w-R}" y2="{py(t):.1f}" stroke="#ddd"/>'
                 f'<text x="{L-6}" y="{py(t)+4:.1f}" text-anchor="end">{t:g}</text>')
    o.append(f'<rect x="{L}" y="{T}" width="{w-L-R}" height="{h-T-B}" fill="none" stroke="#333"/>')
    o.append(f'<text x="{(L+w-R)/2}" y="{h-8}" text-anchor="middle">{_esc(xlabel)}</text>')
    o.append(f'<text x="14" y="{(T+h-B)/2}" text-anchor="middle" transform="rotate(-90 14 {(T+h-B)/2})">{_esc(ylabel)}</text>')
    if sp_line:
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(*sp_line))
        o.append(f'<polyline points="{pts}" fill="none" stroke="#000" stroke-dasharray="6 4" stroke-width="1.2"/>')
    for i, (lab, xs, ys) in enumerate(series):
        c = COLORS[i % len(COLORS)]
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(xs, ys) if not math.isnan(y))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.4"/>')
        ly = T + 14 + 16 * i
        o.append(f'<line x1="{w-R+8}" y1="{ly-4}" x2="{w-R+28}" y2="{ly-4}" stroke="{c}" stroke-width="2"/>'
                 f'<text x="{w-R+32}" y="{ly}">{_esc(lab)}</text>')
    if sp_line:
        ly = T + 14 + 16 * len(series)
        o.append(f'<line x1="{w-R+8}" y1="{ly-4}" x2="{w-R+28}" y2="{ly-4}" stroke="#000" stroke-dasharray="6 4"/>'
                 f'<text x="{w-R+32}" y="{ly}">设定值</text>')
    o.append("</svg>")
    return "\n".join(o)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _decimate(xs, ys, n=1500):
    if len(xs) <= n:
        return xs, ys
    k = math.ceil(len(xs) / n)
    return xs[::k], ys[::k]


# ---------------- 主流程 ----------------
def build(files, y, sp, u=None, u_limit=None, source="", params=None, reqs=(), title="", band=0.05,
          out=pathlib.Path("report"), pre_s=0.2, window=None, req_file=None, item=None):
    if source not in ("board", "sim"):
        raise ReportError("--source 必须写 board（实物）或 sim（仿真）：报告里不能分不清实测和仿真")
    src_txt = "实物" if source == "board" else "仿真"
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for i, f in enumerate(files, 1):
        cols, note = load_run(pathlib.Path(f))
        for c in (y, sp) + ((u,) if u else ()):
            if c not in cols:
                raise ReportError(f"{pathlib.Path(f).name}: 没有列 {c}（有：{', '.join(k for k in cols if k != 't_s')}）")
        if note.startswith("sim:") and source == "board":
            raise ReportError(f"{pathlib.Path(f).name}: 录像来自 {note}，是仿真，不能标 --source board")
        t = cols["t_s"]
        m = step_metrics(t, cols[y], cols[sp], band=band, u=cols[u] if u else None, u_limit=u_limit)
        runs.append((i, pathlib.Path(f).name, t, cols, m))
    reqs = list(reqs)

    # 表头
    shown = list(ORDER)
    hdr = ["次", "文件", "数据来源"] + [f"{REQ_KEYS[k][1]}({REQ_KEYS[k][2]})" for k in shown] + ["是否满足"]
    rows = []
    for i, name, _t, _c, m in runs:
        if not m.ok:
            rows.append([str(i), name, src_txt] + ["—"] * len(shown) + [f"无法计算：{m.reason}"])
            continue
        vals = [fmt(metric_val(m, k)) for k in shown]
        if reqs:
            bad = [f"{REQ_KEYS[k][1]}{op}{lim:g}" for k, op, lim in reqs if not judge(metric_val(m, k), op, lim)]
            ok = "满足" if not bad else "不满足（" + "、".join(bad) + "）"
        else:
            ok = "未给要求"
        rows.append([str(i), name, src_txt] + vals + [ok])
    good = [r for r in runs if r[4].ok]
    summary = []
    if good:
        for lab, agg in (("平均", "mean"), ("最差", "worst")):
            cells = []
            for k in shown:
                vs = [metric_val(m, k) for *_, m in good]
                if any(v is None for v in vs):
                    cells.append("未进带" if agg == "worst" else "—")
                    continue
                if agg == "mean":
                    cells.append(fmt(sum(vs) / len(vs)))
                else:
                    cells.append(fmt(max(vs)))
            summary.append([lab, f"{len(good)}/{len(runs)} 次有效", src_txt] + cells + [""])
        if reqs:
            n_ok = sum(1 for r in rows if r[-1] == "满足")
            nbad = len(runs) - len(good)
            summary.append(["满足率", f"{n_ok}/{len(runs)}" + (f"（{nbad} 次无法计算，算不满足）" if nbad else ""), src_txt] + [""] * len(shown) + [""])

    # 曲线：阶跃起点对齐，只画 [-pre_s, win]。win 没给就取 3×最长调节时间（没进带的按 5 s），且不超过录像长度
    series, sp_xy, band_xy = [], None, None
    if window is None:
        st = [m.settling_s if m.settling_s is not None else 5.0 for *_, m in good]
        window = max(1.0, 3.0 * max(st)) if st else 5.0
    pre_s = min(pre_s, 0.1 * window)
    for i, _name, t, cols, m in runs:
        if not m.ok:
            continue
        xs = [ti - m.t0 for ti in t]
        keep = [k for k, x in enumerate(xs) if -pre_s <= x <= window]
        xk, yk = _decimate([xs[k] for k in keep], [cols[y][k] for k in keep])
        series.append((f"第 {i} 次", xk, yk))
        spk = _decimate([xs[k] for k in keep], [cols[sp][k] for k in keep])
        amp = abs(m.target - m.y0)
        bnd = (m.target - band * amp, m.target + band * amp)
        if sp_xy is None:
            sp_xy, band_xy = spk, bnd
        one = svg_plot([(f"第 {i} 次", xk, yk)], spk, bnd,
                       f"{title or '阶跃响应'} 第 {i} 次（{src_txt}）", "时间 / s（0 = 阶跃时刻）", y)
        (out / f"run_{i}.svg").write_text(one, encoding="utf-8")
    if series:
        (out / "step.svg").write_text(svg_plot(series, sp_xy, band_xy, f"{title or '阶跃响应'}（{src_txt}，{len(series)} 次叠加）",
                                               "时间 / s（0 = 阶跃时刻）", y), encoding="utf-8")

    # 参数表
    ptab = []
    if params:
        pj = json.loads(pathlib.Path(params).read_text(encoding="utf-8"))
        vals = pj.get("values", pj)
        ptab = [(k, vals[k]) for k in sorted(vals)]
        pnote = f"来源：{pathlib.Path(params).name}" + (f"（{pj['time']}）" if "time" in pj else "") + (f"，备注：{pj['note']}" if pj.get("note") else "")
    else:
        pnote = "（未提供参数快照：用 --params 指定工作台存下的快照 json，避免报告参数和实际烧录的不一致）"

    # 写 csv
    with open(out / "results.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(hdr)
        w.writerows(rows + summary)

    # 写 md
    L = [f"# {title or '测试结果'}", "",
         f"> 数据来源：**{src_txt}**，{len(runs)} 次。由 `tools/report.py` 从录像生成，指标与工作台同一算法"
         f"（误差带 ±{band*100:g}%，调节时间 = 最后一次离开误差带的时刻）。"
         + ("**仿真数据，不得写成实测。**" if source == "sim" else ""), "",
         "## 测试条件", "", "（待填：场地、电源电压、负载、初始位置、测试仪器——这些录像里没有，别让工具编）", "",
         "## 控制参数", "", pnote, ""]
    if ptab:
        L += ["| 参数 | 值 |", "|---|---|"] + [f"| {k} | {v:g} |" if isinstance(v, (int, float)) else f"| {k} | {v} |" for k, v in ptab] + [""]
    L += ["## 测试结果", ""]
    if reqs:
        L += ["题目要求：" + "，".join(f"{REQ_KEYS[k][1]} {op} {lim:g}{REQ_KEYS[k][2]}" for k, op, lim in reqs), ""]
    L += ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    L += ["| " + " | ".join(r) + " |" for r in rows + summary]
    L += ["", "## 曲线", ""]
    if series:
        L += ["![阶跃响应叠加](step.svg)", "", "每次单独：" + "、".join(f"[第 {i} 次](run_{i}.svg)" for i, *_r in runs if _r[-1].ok), ""]
    L += ["## 误差分析", "", "（待填：误差来源按大小排序——这一节要人写，工具只给数）", ""]
    if req_file:
        L += evidence_section(req_file, item, source, rows, len(runs), bool(reqs), out)
    (out / "results.md").write_text("\n".join(L), encoding="utf-8")
    return {"runs": len(runs), "valid": len(good), "rows": rows, "summary": summary, "out": str(out)}


def evidence_section(req_file, item, source, rows, n_runs, has_reqs, out) -> list[str]:
    """把 requirements.yaml 里该评分项的证据行（与 tools/req.py evidence 同一函数）带进报告，并给出本次录像的 evidence 建议。
    层只会建议 sim / bench：现场（field）要按题目测法完整走一遍，由人判断后手写，工具不替人宣布。"""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import datetime
    import req as R
    d = R.load(pathlib.Path(req_file))
    its = [i for i in d["items"] if i["id"] == item]
    if not its:
        raise ReportError(f"{req_file} 里没有评分项 {item}")
    n_ok = sum(1 for r in rows if r[-1] == "满足")
    res = "TODO（没给 --req，判不了）" if not has_reqs else ("pass" if n_ok == n_runs else "partial" if n_ok else "fail")
    lay = "bench" if source == "board" else "sim"
    return ["## 评分项证据（requirements.yaml）", "", R.render_evidence(d, its),
            f"本次 {n_runs} 次录像满足 {n_ok} 次 → 建议追加到 {item}.evidence（路径改成相对 requirements.yaml；目录按 docs/verify/README.md 命名）：", "",
            f"```yaml\n- {{ path: {out.as_posix()}, layer: {lay}, date: \"{datetime.date.today():%Y-%m-%d}\", result: {res} }}\n```", ""]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", help=".dzlog 或 .csv，每个文件一次测试")
    ap.add_argument("--y", required=True, help="被控量列名（例 y）")
    ap.add_argument("--sp", required=True, help="设定值列名（例 sp）")
    ap.add_argument("--u", help="控制量列名（判饱和用，可选）")
    ap.add_argument("--u-limit", type=float, help="控制量限幅（配合 --u）")
    ap.add_argument("--source", required=True, choices=["board", "sim"], help="board=实物 sim=仿真（必填）")
    ap.add_argument("--params", help="参数快照 json（工作台存的快照）")
    ap.add_argument("--req", action="append", default=[], help="题目要求，例 overshoot<=10（可多次）")
    ap.add_argument("--band", type=float, default=0.05, help="误差带（默认 0.05 = ±5%%；题目要求 2%% 就填 0.02）")
    ap.add_argument("--window", type=float, help="曲线画阶跃后多少秒（默认 3×最长调节时间）")
    ap.add_argument("--title", default="")
    ap.add_argument("-o", "--out", default="report")
    ap.add_argument("--req-file", help="requirements.yaml：把 --item 那一项的合规/计分证据行带进报告")
    ap.add_argument("--item", help="评分项编号，例 B3（配合 --req-file）")
    a = ap.parse_args(argv)
    if bool(a.req_file) != bool(a.item):
        ap.error("--req-file 与 --item 要一起给")
    try:
        r = build(a.files, a.y, a.sp, a.u, a.u_limit, a.source, a.params, parse_req(a.req), a.title, a.band, pathlib.Path(a.out), window=a.window,
                  req_file=a.req_file, item=a.item)
    except ReportError as e:
        print(f"report: {e}", file=sys.stderr)
        return 2
    print(f"report: {r['valid']}/{r['runs']} 次可算 → {r['out']}/results.md、results.csv、step.svg")
    for row in r["rows"]:
        if row[-1].startswith("无法计算"):
            print(f"  第 {row[0]} 次 {row[1]}: {row[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
