"""赛前全绿检查 + 封箱清单（docs/17）。

= 自检（doctor，电脑环境）+ 板子/工程的“上场前状态”：板子在线、板上固件就是当前固件源码（烧录那次提交之后固件相关目录没改；strict = 必须是 HEAD）、
板上参数 = 固件默认值（否则复位就丢）、急停未锁、没有未确认的严重告警、最近 60 s 链路 0 坏 0 丢、仓库工作区干净。
只读：不发任何参数、不改文件；导出清单是唯一的写操作（写到 ~/.dzbench/seal/）。
通用：不认任何参数名，按 schema 和会话状态判断。
"""
from __future__ import annotations

import pathlib
import subprocess
import time

LEVEL_ORDER = {"fail": 0, "warn": 1, "ok": 2}
# 人工项：工具看不到，清单里留空框
MANUAL = ["电池充满并测过空载电压", "所有螺丝/紧定螺钉拧紧，轮子/联轴器无松动", "线束扎好，电机线与信号线分开走",
          "急停/电源开关现场按过一次有效", "备用电池、备用保险、USB 线、下载器装箱", "固件 .hex/.bin 与本清单一起拷进 U 盘"]


def _it(id_, name, level, msg, fix=""):
    return {"id": id_, "name": name, "level": level, "msg": msg, "fix": fix}


def _git(repo: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


# 会进固件二进制的路径：这些自烧录那次提交以来没变 = 板上固件就是现在的源码（只改文档/上位机不算）
FW_PATHS = ("firmware", "ports", "apps", "boards", "examples", "third_party", "tools", "Makefile", "mk")


def fw_item(rev: int | None, repo: str | None, strict: bool = False) -> dict:
    """固件版本判定。默认：板上那次提交到 HEAD 之间固件相关路径没改、工作区这些路径也干净；strict：必须就是 HEAD。"""
    name = "固件 = 仓库 HEAD 且无未提交改动" if strict else "固件 = 当前固件源码（烧录后固件相关目录没改）"
    if not rev:
        return _it("fw_rev", "固件版本", "warn", "板子没报版本（Keil/CCS 编译没传 DZ_FW_REV）", "用 make 编译烧录，或核对 .hex 生成时间")
    h = f"{rev & 0x0FFFFFFF:07x}"
    if rev & 0x80000000:
        return _it("fw_rev", name, "fail", f"板上 {h}+改动：烧的是带未提交改动的固件", "提交后重新编译烧录（带改动的固件复现不了）")
    head = _git(repo, "rev-parse", "--short=7", "HEAD") if repo else None
    if head is None:
        return _it("fw_rev", name, "warn", f"板上 {h}，读不到仓库 HEAD", "")
    if head.startswith(h):
        return _it("fw_rev", name, "ok", f"板上 {h} = HEAD")
    if strict:
        return _it("fw_rev", name, "fail", f"板上 {h}，仓库 HEAD {head}", "重新编译烧录 HEAD（严格模式）")
    if _git(repo, "cat-file", "-e", f"{h}^{{commit}}") is None:
        return _it("fw_rev", name, "fail", f"板上 {h} 不在本仓库历史里", "烧的不是这个仓库的固件，重新编译烧录")
    paths = [p for p in FW_PATHS if (pathlib.Path(repo) / p).exists()]
    # 板上那次提交 ↔ 工作区（含已提交和未提交的改动）+ 没跟踪的新文件
    changed = (_git(repo, "diff", "--name-only", h, "--", *paths) or "").splitlines()
    changed += (_git(repo, "ls-files", "--others", "--exclude-standard", "--", *paths) or "").splitlines()
    changed = [c for c in changed if c.strip()]
    if changed:
        more = f" 等 {len(changed)} 个" if len(changed) > 3 else ""
        return _it("fw_rev", name, "fail", f"板上 {h} 之后改过固件相关文件：{'、'.join(changed[:3])}{more}", "重新编译烧录")
    return _it("fw_rev", name, "ok", f"板上 {h}，HEAD {head}：之后只改了文档/上位机")


def board_items(s, repo: str | None, strict: bool = False) -> list[dict]:
    out = []
    st = s.status()
    if not st["connected"] or st.get("replay"):
        return [_it("board", "板子在线", "fail", "没连板子（或在回放）", "连上比赛用的那块板再查")]
    out.append(_it("board", "板子在线", "ok" if st["alive"] else "fail",
                   "心跳正常" if st["alive"] else "连着但没心跳", "" if st["alive"] else "看板子是否上电、跑的是不是工作台固件"))
    out.append(fw_item(s.fw_rev, repo, strict))
    if s.schema:
        diff = [f"{p['name']} 板上 {s.params.get(p['name'])} ≠ 默认 {p['default']}" for p in s.schema.params
                if s.params.get(p["name"]) is not None and abs(float(s.params[p["name"]]) - float(p["default"])) > 1e-6 * max(1.0, abs(float(p["default"])))]
        missing = [p["name"] for p in s.schema.params if s.params.get(p["name"]) is None]
        lvl = "fail" if diff else "warn" if missing else "ok"
        out.append(_it("params", "板上参数 = 固件默认值", lvl,
                       "；".join(diff) if diff else (f"没读到：{'、'.join(missing)}" if missing else f"{len(s.schema.params)} 个一致"),
                       "" if lvl == "ok" else "调好的值先“定稿”写回 yaml 并重烧，否则板子一复位就回到旧值" if diff else "点参数区“读取”"))
    out.append(_it("estop", "急停未锁存", "fail" if s.tx_locked else "ok", "已锁存" if s.tx_locked else "正常",
                   "确认安全后按 R 解除" if s.tx_locked else ""))
    tl = s.timeline
    un = [e for e in tl.history() if e["kind"] in ("estop", "watchdog", "crc") and e["i"] > tl.acked]
    out.append(_it("alerts", "没有未确认的严重告警", "warn" if un else "ok",
                   f"{len(un)} 条：" + "；".join(e["text"] for e in un[-3:]) if un else "无", "看完底部告警条再点“知道了”" if un else ""))
    cells = s.health.history()[-60:]
    if len(cells) < 10:
        out.append(_it("link", "链路最近 60 s 无坏帧/丢帧", "warn", f"只有 {len(cells)} 秒数据", "连着跑满 1 分钟再查"))
    else:
        bad, drop = sum(c["crc"] for c in cells), sum(c["drops"] for c in cells)
        out.append(_it("link", "链路最近 60 s 无坏帧/丢帧", "ok" if not bad and not drop else "warn",
                       f"{len(cells)} s：坏 {bad}、丢 {drop}", "" if not bad and not drop else "查共地、线长、电机线是否和串口线捆在一起"))
    return out


def repo_items(repo: str | None) -> list[dict]:
    if not repo:
        return []
    st = _git(repo, "status", "--porcelain")
    if st is None:
        return [_it("git", "工程仓库已提交", "warn", f"{repo} 不是 git 仓库", "")]
    n = len([x for x in st.splitlines() if x.strip()])
    return [_it("git", "工程仓库已提交", "ok" if not n else "fail", "工作区干净" if not n else f"{n} 个文件没提交",
                "" if not n else "提交后再编译烧录，封箱清单才能对上版本")]


def run(s, repo: str | None, doctor_items: list[dict], strict: bool = False) -> dict:
    items = [dict(i, group="电脑") for i in doctor_items] + [dict(i, group="板子") for i in board_items(s, repo, strict)] + \
            [dict(i, group="工程") for i in repo_items(repo)]
    worst = min((LEVEL_ORDER[i["level"]] for i in items), default=2)
    return {"items": items, "all_green": worst == 2, "fails": sum(i["level"] == "fail" for i in items),
            "warns": sum(i["level"] == "warn" for i in items), "t": time.strftime("%Y-%m-%d %H:%M:%S")}


def seal_text(r: dict, s, repo: str | None) -> str:
    mk = {"ok": "✓", "warn": "!", "fail": "✗"}
    rev = s.fw_rev
    L = ["# 封箱清单", "", f"- 时间：{r['t']}（本机时区）",
         "- 结论：" + ("全绿" if r["all_green"] else f"未全绿（✗ {r['fails']}、! {r['warns']}）"),
         f"- 板子：{s.port or '—'} · 板 ID {f'{s.board_uid:08X}' if s.board_uid else '未知'} · 固件 {f'{rev & 0x0FFFFFFF:07x}' + ('+改动' if rev and rev & 0x80000000 else '') if rev else '未知'}",
         f"- 参数表：{f'{s.schema.hash:08X}' if s.schema else '—'} · 仓库：{repo or '—'} @ {_git(repo, 'rev-parse', '--short=7', 'HEAD') if repo else '—'}",
         "", "## 自动检查", "", "| | 分组 | 项 | 结果 | 处理 |", "|---|---|---|---|---|"]
    for i in r["items"]:
        L.append(f"| {mk[i['level']]} | {i['group']} | {i['name']} | {i['msg']} | {i.get('fix', '')} |".replace("\n", " "))
    if s.schema:
        L += ["", "## 板上参数（上位机记的板子回报值）", "", "| 参数 | 值 | 默认 |", "|---|---|---|"]
        L += [f"| {p['name']} | {s.params.get(p['name'], '—')} | {p['default']} |" for p in s.schema.params]
    L += ["", "## 人工确认（打勾后签字）", ""] + [f"- [ ] {m}" for m in MANUAL] + ["", "检查人：________　复核：________", ""]
    return "\n".join(L)


def export(r: dict, s, repo: str | None, base: pathlib.Path) -> str:
    d = base / "seal"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"封箱-{time.strftime('%Y%m%d-%H%M%S')}.md"
    p.write_text(seal_text(r, s, repo), encoding="utf-8", newline="\n")
    return str(p)
