#!/usr/bin/env python3
"""第 2 步 方案选型：读第 1 步的 requirements.yaml，按能力标签从器件库出候选、替代和禁用原因。

  python3 tools/scheme.py requirements.yaml -o out/            出 options.md：每个需要的能力 → 候选表（按仓库支持程度排）
  python3 tools/scheme.py requirements.yaml --scheme scheme.yaml -o out/
                                                             再核对选定方案：选的件真能提供该能力、没被规则禁用、
                                                             备选是不同件、串口够用；出 scheme.md（含系统框图 mermaid）
  scheme.yaml 字段：mcu / mcu_reason / picks{能力: 件} / fallback{能力: 件} / reasons{能力: 理由} / offboard[不接主控的能力]
  python3 tools/scheme.py requirements.yaml --init-scheme scheme.yaml   按排序第一名起稿 scheme.yaml（全标“待定”）

器件库：tools/catalog/parts.yaml（schema/parts.schema.json），加器件只改它。工具只做筛选、排序和一致性检查，不替人拍板：
排序只看“本仓库支持程度”（上板 > 仿真 > 编译 > 无驱动），性能好坏写在 pros/cons 里由人权衡。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import jsonschema
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import req  # noqa: E402  第 1 步的加载/校验

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / "tools" / "catalog" / "parts.yaml"
RANK = {"上板": 0, "仿真": 1, "编译": 2, "无驱动": 3}


def load_catalog(p: pathlib.Path = CATALOG) -> dict[str, dict]:
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    jsonschema.validate(d, json.loads((ROOT / "schema" / "parts.schema.json").read_text(encoding="utf-8")))
    parts = {}
    for x in d["parts"]:
        if x["id"] in parts:
            raise ValueError(f"器件库 id 重复：{x['id']}")
        parts[x["id"]] = x
    return parts


def catalog_problems(parts: dict[str, dict]) -> list[str]:
    """器件库自洽：替代件存在、repo 路径存在、有仓库支持的不能标无驱动。"""
    bad = []
    for x in parts.values():
        for s in x["substitutes"]:
            if s not in parts:
                bad.append(f"{x['id']}：替代件 {s} 不在库里")
        for r in x["repo"]:
            if not (ROOT / r).exists():
                bad.append(f"{x['id']}：repo 路径不存在 {r}（模块删了/改名了？）")
        if x["status"] != "无驱动" and not x["repo"]:
            bad.append(f"{x['id']}：status={x['status']} 但没有 repo 证据")
    return bad


def needs_of(r: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for it in r["items"]:
        for n in it.get("needs", []):
            out.setdefault(n, []).append(it)
    for c in r.get("constraints", []):
        for n in c.get("require", []):
            out.setdefault(n, [])
    return out


def forbidden(r: dict) -> dict[str, str]:
    return {t: c["id"] for c in r.get("constraints", []) for t in c.get("forbid", [])}


def candidates(parts, need: str, forb: dict[str, str]) -> tuple[list[dict], list[tuple[dict, str]]]:
    ok, banned = [], []
    for x in parts.values():
        if need not in x["provides"]:
            continue
        hit = [t for t in x.get("tags", []) + x["provides"] if t in forb]
        (banned.append((x, "、".join(f"{forb[t]}（{t}）" for t in hit))) if hit else ok.append(x))
    ok.sort(key=lambda x: (RANK[x["status"]], x["id"]))
    return ok, banned


def weight(items: list[dict]) -> float:
    return sum(i.get("score", 0) for i in items)


def render_options(r: dict, parts) -> str:
    nd, forb = needs_of(r), forbidden(r)
    L = [f"# {r['problem']['code']} 方案选型 —— 候选", "",
         "> tools/scheme.py 生成。排序只按本仓库支持程度（上板 > 仿真 > 编译 > 无驱动），不代表性能优劣；规格为典型值，以手册为准。", ""]
    if forb:
        L += ["规则禁用：" + "；".join(f"`{t}`（{c}）" for t, c in forb.items()), ""]
    for n in sorted(nd, key=lambda k: -weight(nd[k])):
        ok, banned = candidates(parts, n, forb)
        src = "、".join(i["id"] for i in nd[n]) or "规则要求"
        L += [f"## `{n}` —— 牵涉 {weight(nd[n]):g} 分（{src}）", ""]
        if not ok:
            L += ["**库里没有可用候选**：加进 tools/catalog/parts.yaml，或回第 1 步确认这个能力是否必须。", ""]
        else:
            L += ["| 候选 | 仓库支持 | 优点 | 缺点 | 风险 | 替代 |", "|---|---|---|---|---|---|"]
            for x in ok:
                L.append(f"| {x['name']}（`{x['id']}`） | {x['status']} | {'；'.join(x['pros'])} | {'；'.join(x['cons'])} | "
                         f"{'；'.join(x.get('risks', [])) or '—'} | {', '.join(x['substitutes']) or '—'} |")
            L.append("")
        for x, why in banned:
            L.append(f"- ✗ {x['name']}（`{x['id']}`）：被 {why} 禁用")
        if banned:
            L.append("")
    L += ["## 主控", "", "| 主控 | 内核 | Flash/RAM KB | 串口 | IDE | 仓库支持 | 缺点 |", "|---|---|---|---|---|---|---|"]
    for x in sorted((p for p in parts.values() if p["kind"] == "mcu"), key=lambda p: p["specs"].get("flash_kb", 0)):
        s = x["specs"]
        L.append(f"| {x['name']}（`{x['id']}`） | {s.get('core', '')} | {s.get('flash_kb', '?')}/{s.get('ram_kb', '?')} | "
                 f"{s.get('uart', '?')} | {s.get('ide', '')} | {x['status']} | {'；'.join(x['cons'])} |")
    return "\n".join(L) + "\n"


def check_scheme(r: dict, s: dict, parts) -> tuple[list[str], list[str]]:
    err, warn = [], []
    nd, forb = needs_of(r), forbidden(r)
    picks, fb = s.get("picks", {}), s.get("fallback", {})
    mcu = parts.get(s.get("mcu", ""))
    if not mcu or mcu["kind"] != "mcu":
        err.append(f"mcu={s.get('mcu')} 不是库里的主控")
    for n in nd:
        if n not in picks:
            warn.append(f"`{n}` 还没选（牵涉 {weight(nd[n]):g} 分）")
    for n in picks:
        if n not in nd:
            warn.append(f"`{n}` 选了件但第 1 步没人需要它（多余？）")
    for tbl, label in ((picks, "选定"), (fb, "备选")):
        for n, pid in tbl.items():
            x = parts.get(pid)
            if not x:
                err.append(f"{label} {n}={pid} 不在器件库"); continue
            if n not in x["provides"]:
                err.append(f"{label} {n}={pid}：它不提供 {n}")
            hit = [t for t in x.get("tags", []) + x["provides"] if t in forb]
            if hit:
                err.append(f"{label} {n}={pid}：被 {forb[hit[0]]} 禁用（{hit[0]}）")
            if label == "选定" and x["status"] == "无驱动":
                warn.append(f"{n}={pid}：仓库没有驱动，要自己写（算进工期）")
    for n, pid in fb.items():
        if picks.get(n) == pid:
            err.append(f"备选 {n} 和选定是同一个件 {pid}，等于没有备选")
    for n in picks:
        if n not in fb and nd.get(n) and weight(nd[n]) >= 20:
            warn.append(f"`{n}` 牵涉 {weight(nd[n]):g} 分但没写备选")
    if mcu:
        off = set(s.get("offboard", []))           # 不接主控的能力（图传独立链路等），不占串口
        chosen = {picks[n] for n in picks if picks[n] in parts and n not in off}
        uarts = sum(1 for p in chosen if parts[p].get("bus") == "uart") + (1 if s.get("debug_link_uart", True) else 0)
        have = mcu["specs"].get("uart", 0)
        if uarts > have:
            err.append(f"串口不够：选定件 {uarts - (1 if s.get('debug_link_uart', True) else 0)} 个 + 调试链路 1 个 > {mcu['id']} 的 {have} 个")
        elif uarts == have:
            warn.append(f"串口刚好用满（{uarts}/{have}），没有余量")
    return err, warn


def render_scheme(r: dict, s: dict, parts) -> str:
    nd = needs_of(r)
    mcu = parts[s["mcu"]]
    L = [f"# {r['problem']['code']} 选定方案", "", f"主控：**{mcu['name']}**　理由：{s.get('mcu_reason', '（未写）')}", "",
         "| 能力 | 牵涉分值 | 选定 | 理由 | 备选 | 仓库支持 |", "|---|---|---|---|---|---|"]
    for n in sorted(s.get("picks", {}), key=lambda k: -weight(nd.get(k, []))):
        x = parts[s["picks"][n]]
        f = parts.get(s.get("fallback", {}).get(n, ""), {}).get("name", "—")
        L.append(f"| `{n}` | {weight(nd.get(n, [])):g} | {x['name']} | {s.get('reasons', {}).get(n, '（未写）')} | {f} | {x['status']} |")
    L += ["", "## 系统框图", "", "```mermaid", "flowchart LR", f"  MCU[\"{mcu['name']}\"]"]
    seen, off = set(), set(s.get("offboard", []))
    for n, pid in s.get("picks", {}).items():
        x = parts[pid]
        if pid in seen:
            continue
        seen.add(pid)
        if n in off:
            L += [f"  {pid}[\"{x['name'].split('（')[0]}（独立，不接主控）\"]"]
            continue
        arrow = f"MCU -- {x.get('bus', '')} --> {pid}" if x["kind"] in ("actuator", "ui", "link") and "ui.key" not in x["provides"] \
            else f"{pid} -- {x.get('bus', '')} --> MCU"
        L += [f"  {pid}[\"{x['name'].split('（')[0]}\"]", f"  {arrow}"]
    L.append("```")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("req"); ap.add_argument("-o"); ap.add_argument("--scheme"); ap.add_argument("--init-scheme")
    ap.add_argument("--catalog", default=str(CATALOG))
    ns = ap.parse_args(argv)
    parts = load_catalog(pathlib.Path(ns.catalog))
    bad = catalog_problems(parts)
    for b in bad:
        print("✗ 器件库：", b)
    if bad:
        return 1
    rp = pathlib.Path(ns.req)
    r = req.load(rp)
    err, _ = req.check(r, rp.parent)
    if err:
        print("✗ 第 1 步文件有错误，先跑 tools/req.py check"); return 1
    if ns.init_scheme:
        out = pathlib.Path(ns.init_scheme)
        if out.exists():
            sys.exit(f"✗ {out} 已存在，不覆盖")
        forb = forbidden(r)
        picks = {n: c[0]["id"] for n in needs_of(r) if (c := candidates(parts, n, forb)[0])}
        mcus = sorted((p for p in parts.values() if p["kind"] == "mcu"), key=lambda p: (RANK[p["status"]], -p["specs"].get("uart", 0)))
        d = {"mcu": mcus[0]["id"], "mcu_reason": "待定", "picks": picks, "fallback": {}, "reasons": {n: "待定" for n in picks}}
        out.write_text("# 由 tools/scheme.py --init-scheme 起稿：按仓库支持程度取第一名，逐项改成你们的决定并写理由\n"
                       + yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"写入 {out}（{len(picks)} 项，全部待定）"); return 0
    if ns.o:
        o = pathlib.Path(ns.o); o.mkdir(parents=True, exist_ok=True)
        (o / "options.md").write_text(render_options(r, parts), encoding="utf-8")
        print(f"写入 {o}/options.md")
    if ns.scheme:
        s = yaml.safe_load(pathlib.Path(ns.scheme).read_text(encoding="utf-8"))
        e, w = check_scheme(r, s, parts)
        for x in e:
            print("✗", x)
        for x in w:
            print("!", x)
        if e:
            return 1
        if ns.o:
            (pathlib.Path(ns.o) / "scheme.md").write_text(render_scheme(r, s, parts), encoding="utf-8")
            print(f"写入 {ns.o}/scheme.md")
        print(f"scheme: 通过（{len(w)} 提醒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
