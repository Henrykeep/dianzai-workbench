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
_UNIT = (r"(kHz|MHz|Hz|mV|μV|uV|kV|V|mA|μA|uA|A|kW|mW|W|kΩ|MΩ|Ω|dBm|dB|ms|μs|us|ns|km/h|m/s|cm/s|°/s|r/min|rpm|"
         r"cm|mm|km|m|°|rad|%|‰|℃|kg|g|克|N|lx|div|s|秒|分钟|min|小时|h|次|圈|帧|条|个|片|匝)(?![a-zA-Z])")
_UOPT = "(?:" + _UNIT + ")?"
_NUMV = r"([+-]?\d+(?:\.\d+)?)"
_OPW = (r"(≤|≥|<|>|不大于|不超过|不小于|不低于|不少于|不高于|不多于|至少|至多|小于|大于|低于|高于|少于|多于|"
        r"误差的绝对值均?≤|误差的绝对值均?不大于|误差不大于|误差≤|偏差≤)")
_OPS = {"≤": "<=", "不大于": "<=", "不超过": "<=", "不高于": "<=", "不多于": "<=", "至多": "<=", "≥": ">=",
        "不小于": ">=", "不低于": ">=", "不少于": ">=", "至少": ">=", "<": "<", "小于": "<", "低于": "<", "少于": "<",
        ">": ">", "大于": ">", "高于": ">", "多于": ">"}
# 先匹配的模式吃掉文本，后面的不再重复抓：范围 → 带公差 → 比较 → 裸数值（工作条件/设定值）
_M_RANGE = re.compile(_NUMV + r"\s*" + _UOPT + r"\s*(?:~|～|〜|－|—|至|到)\s*" + _NUMV + r"\s*" + _UNIT)
_M_TOL = re.compile(_NUMV + r"\s*" + _UOPT + r"\s*±\s*" + _NUMV + r"\s*" + _UOPT)
_M_CMP = re.compile(_OPW + r"\s*±?\s*" + _NUMV + r"\s*" + _UOPT)
_M_BARE = re.compile(r"(?<![\d.])" + _NUMV + r"\s*" + _UNIT)
_NAME = re.compile(r"([A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff（）()A-Za-z0-9 ]{1,12}?)\s*[=＝:：]?\s*$")


def _name_before(text: str, i: int) -> str:
    """数值前面最近的量名：符号（Uo、fi）优先，否则前面几个汉字。"""
    pre = re.split(r"[，,。；;、：:]", text[max(0, i - 24):i])[-1]
    sym = re.findall(r"([A-Za-zηφθ][A-Za-z0-9_ ]{0,6})\s*[=＝]\s*$", pre)
    if sym:
        return sym[-1].replace(" ", "")
    pre = re.sub(r"(误差的绝对值均?|误差|偏差|为|是|在|均|且|内|时间|≤|≥|<|>|不大于|不超过|不小于|不低于|不少于|不高于|至少|小于|大于|=)+\s*$", "", pre.strip())
    return (pre[-10:].strip() or "待填")


def extract_metrics(text: str) -> list[dict]:
    """原文里每个 数值+单位（范围、±公差、比较、设定值），按出现顺序；名字从前文猜，必须人工核对。"""
    used = [False] * len(text)
    found = []

    def take(m):
        if any(used[m.start():m.end()]):
            return False
        for k in range(m.start(), m.end()):
            used[k] = True
        return True

    for m in _M_RANGE.finditer(text):
        if take(m):
            u = m.group(4) or m.group(2)
            found.append((m.start(), {"name": _name_before(text, m.start()), "op": "in",
                                      "value": [float(m.group(1)), float(m.group(3))], "unit": u}))
    for m in _M_TOL.finditer(text):
        if take(m):
            v, t = float(m.group(1)), float(m.group(3))
            found.append((m.start(), {"name": _name_before(text, m.start()), "op": "in",
                                      "value": [round(v - t, 6), round(v + t, 6)], "unit": m.group(2) or m.group(4) or ""}))
    for m in _M_CMP.finditer(text):
        if take(m):
            op = next((v for k, v in _OPS.items() if m.group(1).endswith(k)), "<=")
            found.append((m.start(), {"name": _name_before(text, m.start()), "op": op, "value": float(m.group(2)), "unit": m.group(3) or ""}))
    for m in _M_BARE.finditer(text):
        if take(m):
            found.append((m.start(), {"name": _name_before(text, m.start()), "op": "==", "value": float(m.group(1)), "unit": m.group(2)}))
    out = []
    for _, d in sorted(found, key=lambda x: x[0]):
        d["how"] = "待填（init 抓到的数值：核对含义；== 多半是工作条件/设定值）"
        out.append(d)
    return out


KEYWORDS = ROOT / "tools" / "catalog" / "needs_keywords.yaml"


def load_keywords(p: pathlib.Path = KEYWORDS) -> dict[str, list[str]]:
    return {k: [str(x) for x in v or []] for k, v in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).items()} if p.exists() else {}


def suggest_needs(text: str, kw: dict[str, list[str]]) -> list[str]:
    t = text.lower()
    return [tag for tag, words in kw.items() if any(w.lower() in t for w in words)]


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


def init_skeleton(text: str, code: str, source: str, kw: dict | None = None) -> dict:
    kw = load_keywords() if kw is None else kw
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
            it["metrics"] = extract_metrics(it["text"])
            it["needs"] = suggest_needs(it["text"], kw)
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


# ── 证据（docs/verify/README.md） ─────────────────────────────────
LOG_RE = re.compile(r"(?:^|/)logs/(\d{8})-(\d{4})_task([BA]\d+|\d+)_(unit|sim|bench|field)/?$")
LAYER_NAME = {"unit": "单元", "sim": "仿真", "bench": "台架", "field": "现场"}
STATUS_ORDER = ["field", "bench", "sim", "unit"]


def status(it: dict) -> str:
    """状态只认 pass 的证据，取最高一层。“准备联调”“仿真通过”都不等于“已得分”——只有现场通过才算。"""
    ev = it.get("evidence", [])
    for lay in STATUS_ORDER:
        if any(e["layer"] == lay and e["result"] == "pass" for e in ev):
            return f"{LAYER_NAME[lay]}通过"
    for lay in STATUS_ORDER:
        if any(e["layer"] == lay and e["result"] == "partial" for e in ev):
            return f"{LAYER_NAME[lay]}部分"
    return "未过" if ev else "未测"


def check_evidence(d: dict, base: pathlib.Path) -> tuple[list[str], list[str]]:
    err, warn = [], []
    for it in d["items"]:
        for e in it.get("evidence", []):
            p = (base / e["path"]).resolve()
            tag = f"{it['id']} 证据 {e['path']}"
            if not p.exists():
                err.append(f"{tag}：路径不存在"); continue
            m = LOG_RE.search(e["path"].replace("\\", "/").rstrip("/") + "/")
            if not m:
                warn.append(f"{tag}：不是 logs/<YYYYMMDD-HHMM>_task<编号>_<层>/ 目录（docs/verify/README.md）"); continue
            day, _hm, task, lay = m.groups()
            if task != it["id"] and str(it.get("test_id")) != task:
                err.append(f"{tag}：目录写的是 task{task}，不是 {it['id']}")
            if lay != e["layer"]:
                err.append(f"{tag}：目录层是 {lay}，evidence.layer 写的 {e['layer']}")
            if day != e["date"].replace("-", ""):
                err.append(f"{tag}：目录日期 {day} 与 date {e['date']} 不一致")
            if p.is_dir():
                files = {f.name for f in p.iterdir()}
                if not files:
                    err.append(f"{tag}：空目录不算证据")
                if lay in ("bench", "field") and "flash.txt" not in files:
                    warn.append(f"{tag}：缺 flash.txt（烧录输出 + 固件版本），说不清测的是哪版固件")
                if lay in ("bench", "field") and not files & {"params.txt", "params_before.txt"}:
                    warn.append(f"{tag}：缺参数回读 params.txt（dzctl params 导出），说不清测的是哪组参数")
        if it["part"] != "other" and not it.get("why"):
            warn.append(f"{it['id']}：没写设计依据 why（答辩会被问“凭什么能达标”）")
    return err, warn


def render_evidence(d: dict, items=None) -> str:
    """合规/计分证据表：评分五元组（操作→验证位置→预期→依据→分值）+ 状态 + 证据 + 禁止表述。"""
    items = items if items is not None else d["items"]
    L = ["| 编号 | 分值 | 操作（怎么测） | 验证位置 | 预期（通过条件） | 设计依据 | 状态 | 证据 | 当前禁止表述 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for i in items:
        how = "；".join(m["how"] for m in i.get("metrics", []) if m.get("how")) or "—"
        where = "、".join(x for x in [i.get("accept") and f"工作台验收 {i['accept']}",
                                       i.get("test_id") is not None and f"测试 {i['test_id']}"] if x) or "人工"
        exp = "；".join(fmt_metric(m) for m in i.get("metrics", [])) or "**缺指标**"
        ev = "<br>".join(f"{LAYER_NAME[e['layer']]} {e['date']} {e['result']}：`{e['path']}`" for e in i.get("evidence", [])) or "—"
        forb = list(i.get("forbidden_claims", []))
        st = status(i)
        if st != "现场通过":
            forb.append(f"“{i['id']} 已得分”（当前只到：{st}）")
        sc = f"{i['score']:g}" if "score" in i else "?"
        L.append(f"| {i['id']} | {sc} | {how} | {where} | {exp} | {i.get('why') or '**未写**'} | {st} | {ev} | {'；'.join(forb)} |")
    tot = sum(i.get("score", 0) for i in items)
    got = {s: sum(i.get("score", 0) for i in items if status(i) == s) for s in ("现场通过", "台架通过", "仿真通过")}
    L += ["", f"分值：总 {tot:g}；现场通过 {got['现场通过']:g}；台架通过 {got['台架通过']:g}；仿真通过 {got['仿真通过']:g}。"
          "只有“现场通过”（按题目测法、按次数完整走一遍）才能说已得分；准备联调 ≠ 已得分。"]
    return "\n".join(L) + "\n"


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
    e = sp.add_parser("evidence", help="合规/计分证据表 → <o>/evidence.md"); e.add_argument("req"); e.add_argument("-o", required=True)
    n = sp.add_parser("newlog", help="按 docs/verify 规范建一个日志目录并打印 evidence 片段")
    n.add_argument("--root", required=True, help="例 docs/verify/2026H"); n.add_argument("--task", required=True); n.add_argument("--layer", required=True, choices=list(LAYER_NAME))
    ns = ap.parse_args(argv)
    if ns.cmd == "init":
        src = pathlib.Path(ns.src)
        d = init_skeleton(read_text(src), ns.code, str(src))
        out = pathlib.Path(ns.o)
        if out.exists():
            sys.exit(f"✗ {out} 已存在，不覆盖（人工改过的拆解不能被草稿冲掉）")
        out.write_text("# 由 tools/req.py init 起稿：分值、指标、子系统、needs 必须对照原文人工核对（needs 按 tools/catalog/needs_keywords.yaml 关键词猜）\n"
                       + yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
        print(f"写入 {out}：评分项 {len(d['items'])} 条、疑似规则约束 {len(d['constraints'])} 条（草稿）")
        return 0
    if ns.cmd == "newlog":
        import datetime
        now = datetime.datetime.now()
        d = pathlib.Path(ns.root) / "logs" / f"{now:%Y%m%d-%H%M}_task{ns.task}_{ns.layer}"
        d.mkdir(parents=True, exist_ok=False)
        (d / "notes.md").write_text(f"# task{ns.task} {LAYER_NAME[ns.layer]} {now:%Y-%m-%d %H:%M}\n\n- 谁测 / 场地 / 电源电压：\n- 现象：\n", encoding="utf-8", newline="\n")
        print(d)
        print(f"evidence 片段（路径改成相对 requirements.yaml）：\n  - {{ path: {d.as_posix()}, layer: {ns.layer}, date: {now:%Y-%m-%d}, result: TODO }}")
        return 0
    p = pathlib.Path(ns.req)
    try:
        d = load(p)
    except jsonschema.ValidationError as e:
        print(f"✗ {p}: {e.message}（位置 {list(e.absolute_path)}）"); return 1
    err, warn = check(d, p.parent)
    e2, w2 = check_evidence(d, p.parent)
    err, warn = err + e2, warn + w2
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
    if ns.cmd == "evidence":
        (out / "evidence.md").write_text(f"# {d['problem']['code']} {d['problem']['title']} —— 合规与计分证据表\n\n"
                                         "> tools/req.py evidence 生成；证据目录规范见 docs/verify/README.md。\n\n" + render_evidence(d),
                                         encoding="utf-8", newline="\n")
        print(f"写入 {out}/evidence.md")
        return 0
    md, rows = render(d)
    (out / "checklist.md").write_text(md, encoding="utf-8")
    with open(out / "checklist.csv", "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    print(f"写入 {out}/checklist.md、checklist.csv（{len(rows) - 1} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
