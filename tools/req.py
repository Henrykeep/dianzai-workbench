#!/usr/bin/env python3
"""第 1 步 读题拆解：题目原文 → requirements.yaml → 按评分项的测试清单（映射到子系统）。

  init  <题目.pdf|.txt> -o requirements.yaml   从原文抽出候选评分项骨架（只是起稿，逐条人工核对）
  check <requirements.yaml>                    校验结构；对照 project.yaml 核对子系统 / 验收 / 测试编号；列出未确认、不可验收项
  checklist <requirements.yaml> -o 目录         生成 checklist.md（贴墙、比赛当天逐项打勾）+ checklist.csv

不编数据：init 只做文字切分和数字/单位抓取，分值、指标、子系统都要人填；没有指标的评分项 check 会报"不可验收"。
格式定义：schema/requirements.schema.json。第 2 步 tools/scheme.py 读同一个文件的 needs / constraints。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import subprocess
import sys

import jsonschema
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "requirements.schema.json"
PART_NAME = {"basic": "基本要求", "advanced": "发挥部分", "other": "其他"}

# ── init：原文 → 骨架 ─────────────────────────────────────────────
# 电赛题目两种常见写法：“基本要求/发挥部分 + （1）（2）”，以及 2026 起“二、要求 + 1. 2. …（N 分）”。
_SEC = re.compile(r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*(\S+)")
_PART = [(re.compile(r"基本要求"), "basic"), (re.compile(r"发挥部分"), "advanced")]
_ITEM = re.compile(r"^\s*(?:[（(]\s*(\d{1,2})\s*[)）]|(\d{1,2})\s*[.．、](?!\d))\s*(.+)")
_SCORE = re.compile(r"[（(]\s*(\d+(?:\.\d+)?)\s*分\s*[)）]\s*$")
_NUM = re.compile(r"(≤|≥|<|>|不大于|不超过|不小于)?\s*([+-±]?\d+(?:\.\d+)?)\s*(cm|mm|m/s|ms|s|m|°|Hz|kHz|V|mA|A|%|次|圈|秒|分钟)(?![a-zA-Z])")
_OPS = {"≤": "<=", "不大于": "<=", "不超过": "<=", "≥": ">=", "不小于": ">=", "<": "<", ">": ">"}
_RULE = re.compile(r"不得|不能|禁止|只能|必须|不允许|不大于|不超过|封存|不予测试|视为|即认为")


def read_text(src: pathlib.Path) -> str:
    if src.suffix.lower() == ".pdf":
        try:
            return subprocess.run(["pdftotext", "-layout", str(src), "-"], check=True,
                                  capture_output=True, text=True).stdout
        except (OSError, subprocess.CalledProcessError) as e:
            sys.exit(f"✗ 读 PDF 失败（需要 poppler 的 pdftotext，或先另存为 .txt）：{e}")
    return src.read_text(encoding="utf-8")


def _join(parts: list[str]) -> str:
    """版式换行会把中文词拆开（“计时停 止”）：两边都是 ASCII 字母数字才补空格。"""
    out = ""
    for t in parts:
        out += (" " if out and out[-1].isascii() and out[-1].isalnum() and t[0].isascii() and t[0].isalnum() else "") + t
    return out


def _paragraphs(text: str):
    """按 (章节, 段落) 产出；段落 = 一个编号项及其续行。跳过“任务”之前的参赛注意事项。"""
    lines = text.splitlines()
    start = next((k for k, l in enumerate(lines) if _SEC.match(l) and "任务" in l), 0)
    sec, buf = "", []
    for l in lines[start:]:
        t = l.strip()
        if not t or re.fullmatch(r"[A-Z]-\s*\d+\s*/\s*\d+|图\s*\d+.*", t):
            continue
        m, im = _SEC.match(l), _ITEM.match(l)
        head = (im.group(3).strip() if im else t).rstrip("：:")
        is_part = any(rx.fullmatch(head) for rx, _ in _PART)       # “1．基本要求” 是小节标题，不是评分项
        if m or im or is_part:
            if buf:
                yield sec, _join(buf)
            buf = []
            if m:
                sec = m.group(1)
            elif is_part:
                sec = head
            else:
                buf = [t]
            continue
        buf.append(t)
    if buf:
        yield sec, _join(buf)


def init_skeleton(text: str, code: str, source: str) -> dict:
    items, rules, n, part = [], [], {"basic": 0, "advanced": 0}, "basic"
    for sec, para in _paragraphs(text):
        para = re.sub(r"\s+", " ", para)
        for rx, p in _PART:
            if rx.search(sec):
                part = p
        m = _ITEM.match(para)
        if m and ("要求" in sec or sec == "发挥部分"):
            body = m.group(3).strip()
            n[part] += 1
            it = {"id": ("B" if part == "basic" else "A") + str(n[part]), "part": part, "text": body,
                  "subsystems": [], "needs": [], "metrics": []}
            sm = _SCORE.search(body)
            if sm:
                it["score"] = float(sm.group(1)); it["text"] = body[:sm.start()].rstrip("。 ")
            for op, v, u in _NUM.findall(it["text"]):
                if op:
                    it["metrics"].append({"name": "待填", "op": _OPS[op], "value": float(v.lstrip("+±")), "unit": u,
                                          "how": "待填（init 抓到的阈值，核对含义）"})
            items.append(it)
        elif "说明" in sec or "要求" in sec or m:
            for sent in re.split(r"(?<=[。；])", para):
                if _RULE.search(sent) and len(sent.strip()) > 4:
                    rules.append({"id": f"R{len(rules) + 1}", "text": sent.strip(), "forbid": [], "confirmed_by": []})
    return {"schema_version": 1, "problem": {"code": code, "title": "待填", "source": source, "confirmed_by": []},
            "constraints": rules, "items": items or [{"id": "B1", "part": "basic", "text": "待填（没认出评分项编号，手动拆）"}]}


# ── check ────────────────────────────────────────────────────────
def load(p: pathlib.Path) -> dict:
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    jsonschema.validate(d, json.loads(SCHEMA.read_text(encoding="utf-8")))
    return d


def check(d: dict, base: pathlib.Path) -> tuple[list[str], list[str]]:
    """返回 (错误, 提醒)。错误 = 结构自相矛盾；提醒 = 还没做完的读题工作。"""
    err, warn = [], []
    ids = [i["id"] for i in d["items"]] + [c["id"] for c in d.get("constraints", [])]
    for x in sorted({i for i in ids if ids.count(i) > 1}):
        err.append(f"编号重复：{x}")
    for it in d["items"]:
        want = {"basic": "B", "advanced": "A"}.get(it["part"])
        if want and not it["id"].startswith(want):
            err.append(f"{it['id']}：part={it['part']} 编号应以 {want} 开头")
    proj = None
    if d["problem"].get("project"):
        pp = (base / d["problem"]["project"]).resolve()
        if not pp.exists():
            err.append(f"problem.project 不存在：{pp}")
        else:
            proj = yaml.safe_load(pp.read_text(encoding="utf-8"))
    if proj:
        subs = {s["name"] for s in proj.get("subsystems", [])}
        acc = {a["name"] for a in (proj.get("link") or {}).get("accept", [])}
        tids = {t["id"] for t in proj.get("tests", [])}
        for it in d["items"]:
            for s in it.get("subsystems", []):
                if s not in subs and not s.startswith("ext:"):
                    err.append(f"{it['id']}：子系统 {s} 不在 project.yaml（有 {sorted(subs)}）")
            if it.get("accept") and it["accept"] not in acc:
                err.append(f"{it['id']}：accept={it['accept']} 不在 project.yaml link.accept")
            if it.get("test_id") is not None and it["test_id"] not in tids:
                err.append(f"{it['id']}：test_id={it['test_id']} 不在 project.yaml tests")
    for it in d["items"]:
        if it["part"] != "other" and not it.get("metrics"):
            warn.append(f"{it['id']}：没有指标 → 不可验收（把“稳定”“尽快”写成数：误差、时间、次数）")
        if it["part"] != "other" and "score" not in it:
            warn.append(f"{it['id']}：没写分值（排优先级要用）")
        if it["part"] != "other" and not it.get("subsystems"):
            warn.append(f"{it['id']}：没映射到子系统")
        for m in it.get("metrics", []):
            if m["name"] == "待填" or "待填" in m.get("how", ""):
                warn.append(f"{it['id']}：指标 {m['value']}{m.get('unit', '')} 还是 init 草稿")
    for c in d.get("constraints", []):
        if len(c.get("confirmed_by", [])) < 1:
            warn.append(f"{c['id']}：规则约束未确认（“{c['text'][:24]}”）")
    if not d["problem"].get("confirmed_by"):
        warn.append("整份拆解还没人签字确认（problem.confirmed_by）——AI/工具拆的必须对照原文")
    return err, warn


# ── checklist ────────────────────────────────────────────────────
def fmt_metric(m: dict) -> str:
    v = m["value"]
    if isinstance(v, bool):
        return f"{m['name']}：{'是' if v else '否'}"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{m['name']} {m['op']} {v}{m.get('unit', '')}"


def render(d: dict) -> tuple[str, list[list[str]]]:
    items = d["items"]
    subs = sorted({s for i in items for s in i.get("subsystems", [])})
    tot = {p: sum(i.get("score", 0) for i in items if i["part"] == p) for p in PART_NAME}
    L = [f"# {d['problem']['code']} {d['problem']['title']} —— 测试清单", "",
         f"原文：{d['problem']['source']}　｜　确认人：{'、'.join(d['problem'].get('confirmed_by', [])) or '**未确认**'}　｜　"
         + " · ".join(f"{PART_NAME[p]} {tot[p]:g} 分" for p in PART_NAME if tot[p]), "",
         "> 由 tools/req.py 从 requirements.yaml 生成，改清单请改 yaml 再生成。每项按次数实测、逐次记录（报告直接用 tools/report.py）。", ""]
    if d.get("constraints"):
        L += ["## 规则约束（违反直接扣分/取消，三人各自对照原文确认）", "", "| 编号 | 约束 | 必须有 | 禁用 | 确认 |", "|---|---|---|---|---|"]
        for c in d["constraints"]:
            L.append(f"| {c['id']} | {c['text']} | {', '.join(c.get('require', [])) or '—'} | {', '.join(c.get('forbid', [])) or '—'} | {'、'.join(c.get('confirmed_by', [])) or '☐'} |")
        L.append("")
    L += ["## 评分项 → 测试", "", "| 编号 | 分值 | 要求 | 指标（通过条件） | 怎么测 | 次数 | 子系统 | 工作台验收 | 结果 |",
          "|---|---|---|---|---|---|---|---|---|"]
    rows = [["编号", "部分", "分值", "要求", "指标", "怎么测", "次数", "子系统", "验收", "测试编号", "结果"]]
    order = sorted(items, key=lambda i: ({"basic": 0, "advanced": 1}.get(i["part"], 2), -i.get("score", 0)))
    for i in order:
        ms = "；".join(fmt_metric(m) for m in i.get("metrics", [])) or "**缺指标**"
        how = "；".join(m["how"] for m in i.get("metrics", []) if m.get("how")) or "—"
        acc = (i.get("accept") or "—") + (f" / 测试 {i['test_id']}" if i.get("test_id") is not None else "")
        sc = f"{i['score']:g}" if "score" in i else "?"
        L.append(f"| {i['id']} | {sc} | {i['text']} | {ms} | {how} | {i.get('runs', 1)} | "
                 f"{', '.join(i.get('subsystems', [])) or '**未映射**'} | {acc} | ☐ |")
        rows.append([i["id"], PART_NAME[i["part"]], str(i.get("score", "")), i["text"], ms, how, str(i.get("runs", 1)),
                     " ".join(i.get("subsystems", [])), i.get("accept", ""), str(i.get("test_id", "")), ""])
    if subs:
        L += ["", "## 子系统 × 评分项（● = 该项要用到；“耦合”= 涉及 2 个以上固件子系统（ext: 不算），单独调好不等于合起来达标）", "",
              "| 编号 | 分值 | " + " | ".join(subs) + " | 耦合 |", "|---|---|" + "---|" * (len(subs) + 1)]
        for i in order:
            s = set(i.get("subsystems", []))
            sc = f"{i['score']:g}" if "score" in i else "?"
            L.append(f"| {i['id']} | {sc} | " + " | ".join("●" if x in s else "" for x in subs) + f" | {'是' if len([x for x in s if not x.startswith('ext:')]) > 1 else ''} |")
        L += ["", "| 子系统 | 牵涉分值 |", "|---|---|"]
        for x in subs:
            L.append(f"| {x} | {sum(i.get('score', 0) for i in items if x in i.get('subsystems', [])):g} |")
    if d.get("estimates"):
        L += ["", "## 量级估算（选型/调参的依据）", "", "| 估算 | 结果 | 依据 |", "|---|---|---|"]
        L += [f"| {e['what']} | {e['value']} | {e['basis']} |" for e in d["estimates"]]
    needs = sorted({n for i in items for n in i.get("needs", [])})
    if needs:
        L += ["", f"## 下一步：方案选型（tools/scheme.py 读本文件）", "", "需要的能力：" + "、".join(f"`{n}`" for n in needs)]
    return "\n".join(L) + "\n", rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("init"); a.add_argument("src"); a.add_argument("-o", required=True); a.add_argument("--code", default="待填")
    b = sp.add_parser("check"); b.add_argument("req"); b.add_argument("--strict", action="store_true", help="提醒也算失败（比赛前用）")
    c = sp.add_parser("checklist"); c.add_argument("req"); c.add_argument("-o", required=True)
    ns = ap.parse_args(argv)
    if ns.cmd == "init":
        src = pathlib.Path(ns.src)
        d = init_skeleton(read_text(src), ns.code, str(src))
        out = pathlib.Path(ns.o)
        if out.exists():
            sys.exit(f"✗ {out} 已存在，不覆盖（人工改过的拆解不能被草稿冲掉）")
        out.write_text("# 由 tools/req.py init 起稿：分值、指标、子系统、needs 必须对照原文人工核对\n"
                       + yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
        print(f"写入 {out}：评分项 {len(d['items'])} 条、疑似规则约束 {len(d['constraints'])} 条（草稿）")
        return 0
    p = pathlib.Path(ns.req)
    try:
        d = load(p)
    except jsonschema.ValidationError as e:
        print(f"✗ {p}: {e.message}（位置 {list(e.absolute_path)}）"); return 1
    err, warn = check(d, p.parent)
    for e in err:
        print("✗", e)
    for w in warn:
        print("!", w)
    if ns.cmd == "check":
        bad = err or (ns.strict and warn)
        print(f"req: {'失败' if bad else '通过'}（{len(err)} 错误，{len(warn)} 提醒）")
        return 1 if bad else 0
    if err:
        return 1
    out = pathlib.Path(ns.o); out.mkdir(parents=True, exist_ok=True)
    md, rows = render(d)
    (out / "checklist.md").write_text(md, encoding="utf-8")
    with open(out / "checklist.csv", "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    print(f"写入 {out}/checklist.md、checklist.csv（{len(rows) - 1} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
