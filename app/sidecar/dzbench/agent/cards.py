"""确认卡的内容：把要执行的动作讲成人话（每步做什么、哪些文件新增/改动、引脚/参数 旧→新），细节可展开。
界面 agent.ts renderAction 只认这一种结构，不再把 JSON 原样摊给人看：

    {"title", "summary", "steps": [{"title", "state": ok|warn|fail, "facts": [str],
                                     "changes": [{"k": file|pin|param|evidence, "name", "old", "new"}], "detail": str}],
     "after": str, "prearm"?: {...}, "error"?: str}
"""
from __future__ import annotations

import difflib
import pathlib
import re

import yaml

from .. import paths

PIN = re.compile(r"^P[A-K]\d{1,2}$")
STEP_CN = {"req": "读题", "scheme": "方案", "import": "导入工程", "scratch": "从零新建", "alloc": "资源分配", "gen": "生成工程", "keil": "Keil 工程"}


# 卡片自带中文标题的 human 级工具（界面 c.title 优先于 agent.ts TOOL_CN）
TITLED = {"iterate_start": "自动迭代调参", "iterate_apply_best": "采用最好参数", "project_fork": "以例题为模板新建项目"}

def _read(p: pathlib.Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def pins(board_yaml: str | None) -> dict[str, str]:
    """board.yaml resources → {信号名: 引脚}（tx/rx/sda/scl 这类多脚的记成 名.tx）。"""
    try:
        d = yaml.safe_load(board_yaml or "") or {}
    except yaml.YAMLError:
        return {}
    out = {}
    for kind, rows in (d.get("resources") or {}).items():
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            nm = str(r.get("name") or kind)
            for k, v in r.items():
                if isinstance(v, str) and PIN.match(v):
                    out[nm if k == "pin" else f"{nm}.{k}"] = v
    return out


def pin_changes(new_yaml: str | None, old_yaml: str | None) -> list[dict]:
    n, o = pins(new_yaml), pins(old_yaml)
    return [{"k": "pin", "name": s, "old": o.get(s), "new": n.get(s)} for s in sorted(set(n) | set(o)) if n.get(s) != o.get(s)]


def file_changes(files: dict[str, str], target: pathlib.Path, rel: str = "", prior: dict | None = None) -> tuple[list[dict], str]:
    """暂存文件 vs 目标目录（prior = 同一张卡前几步将写入的版本，优先比它）：新增 / 改动（+/- 行数）；返回 (changes, 统一 diff)。"""
    ch, diffs = [], []
    for name, txt in sorted(files.items()):
        old = (prior or {}).get(name, _read(target / name))
        if old == txt:
            continue
        a, b = (old or "").splitlines(), txt.splitlines()
        d = list(difflib.unified_diff(a, b, f"{rel}{name}", f"{rel}{name}（写入后）", lineterm="", n=1))
        add = sum(1 for x in d if x.startswith("+") and not x.startswith("+++"))
        rm = sum(1 for x in d if x.startswith("-") and not x.startswith("---"))
        ch.append({"k": "file", "name": rel + name, "old": None if old is None else f"{len(a)} 行",
                   "new": f"+{add} −{rm}" if old is not None else f"新文件 {len(b)} 行"})
        diffs += d[:80] + (["…（还有 %d 行，见项目页）" % (len(d) - 80)] if len(d) > 80 else [])
    return ch, "\n".join(diffs)


def _stage_files(stage: pathlib.Path) -> dict[str, str]:
    return {p.relative_to(stage).as_posix(): t for p in sorted(stage.rglob("*")) if p.is_file() and (t := _read(p)) is not None} if stage.is_dir() else {}


def chain_step(root: pathlib.Path, code: str, s: dict, stage_home: pathlib.Path, prior: dict | None = None) -> dict:
    """project_chain 的一步 → 卡片上一行：做了什么、写哪些文件、引脚怎么变。"""
    step = s["step"]
    st = {"title": STEP_CN.get(step, step), "state": "ok" if s.get("ok") else "fail", "facts": [], "changes": [], "detail": ""}
    if not s.get("ok"):
        st["facts"] = [x for x in (s.get("why"), s.get("fix")) if x]
        return st
    tgt = paths.project_dir(root, code)
    if step == "req":
        st["facts"] = [f"拆出 {s.get('items')} 个评分项"] + [f"· {t}" for t in s.get("first") or []]
    elif step == "scheme":
        st["facts"] = [f"主控 {s.get('mcu')}"] + ([f"⚠ {s['mcu_note']}"] if s.get("mcu_note") else [])
    elif step == "scratch":
        st["facts"] = [f"芯片 {s.get('label')}", f"板名 {s.get('board')}", "写 .ioc 后要你在 CubeMX 点一次 GENERATE CODE"]
        if s.get("others"):
            st["facts"].append(f"另有 {len(s['others'])} 个候选（展开看）")
    elif step == "import":
        st["facts"] = [f"板 boards/{s.get('board')}", f"{s.get('aliases')} 个引脚别名"]
    elif step == "gen":
        st["facts"] = [f"{s.get('files')} 个生成文件"] + ([f"用子系统 {'、'.join(s['subsys'])}"] if s.get("subsys") else []) \
            + ([f"缺子系统 {'、'.join(s['missing'])}（要新建）"] if s.get("missing") else [])
        if s.get("missing"):
            st["state"] = "warn"
    elif step == "keil":
        st["facts"] = ["把工作台模块注入 Keil 工程（dz/ 组、包含路径、宏；幂等）", f"改 {s.get('uvprojx')}，原文件备份为 .bak"]
        st["changes"].append({"k": "file", "name": s.get("uvprojx"), "old": "原工程", "new": "注入 dz/ 组"})
        st["detail"] = s.get("out_tail", "")
        return st
    files = _stage_files(stage_home / code / "stage" / step)
    if step == "scratch":                                  # 从零新建的分配结果落在沙盒 alloc/ 里
        files = {f"alloc/{k}": v for k, v in _stage_files(stage_home / code / "sandbox" / "alloc").items()} | files
    if step in ("req", "scheme", "scratch", "alloc"):
        ch, diff = file_changes(files, tgt, f"projects/{code}/", prior)
        st["changes"] += ch
        st["detail"] = ("其他候选芯片：\n" + "\n".join("  " + x for x in s["others"]) + "\n\n" if s.get("others") else "") + diff
        if prior is not None:
            prior.update(files)
    new_b = files.get("alloc/board.yaml") or files.get("board.yaml")
    if new_b:
        st["changes"] += pin_changes(new_b, _read(tgt / "alloc" / "board.yaml"))
    return st


def build(svc, tool: str, args: dict) -> dict | None:
    """gate 出卡时调：按工具拼卡片内容。未知工具返回 None（卡片只显示标题和按钮）。"""
    from . import steptools
    root = pathlib.Path(svc.gw.root)
    where = "仿真" if svc.sim else "实机"
    if tool == "iterate_start":
        try:
            return {"title": TITLED[tool]} | svc.iterate_card(args)
        except Exception as e:  # noqa: BLE001
            return {"title": TITLED[tool], "error": str(e)}
    if tool == "project_fork":
        from .. import paths as _paths
        return {"title": TITLED[tool], "example": args.get("example"), "code": args.get("code"),
                "dest": str(_paths.projects_dir() / str(args.get("code"))),
                "note": "把内置例题复制成一个新项目目录（例题本身只读、不改）；确认后连仿真板并自动迭代调参"}
    if tool == "iterate_apply_best":
        cur = svc.s.params
        return {"title": TITLED[tool], "where": where, "iter": args.get("iter"), "params_hash": args.get("params_hash"),
                "changes": [{"name": n, "from": cur.get(n), "to": v} for n, v in (args.get("params") or {}).items()
                            if cur.get(n) is None or abs(float(cur[n]) - float(v)) > 1e-9],
                "note": "写入迭代里最好一轮的参数（逐个校验）；掉电保持需再点“保存参数”"}
    if tool == "project_apply":
        c = svc.chains.get(args.get("code")) or {}
        home = steptools._flow(root).home
        prior: dict = {}
        steps = [chain_step(root, args["code"], s, home, prior) for s in c.get("steps") or []]
        nf = sum(1 for s in steps for x in s["changes"] if x["k"] == "file")
        npin = sum(1 for s in steps for x in s["changes"] if x["k"] == "pin")
        return {"title": f"写入项目 {args.get('code')}", "steps": steps,
                "summary": f"{len(c.get('batch') or [])} 步 · {nf} 个文件" + (f" · {npin} 个引脚" if npin else "") + " · 都已在暂存区预览过",
                "after": ("写入后自动：连仿真板 → 一键起步调参 → 评分" if args.get("code") in getattr(svc, "quick", {}) else "按顺序写入工程目录；某步失败就停在那一步，已写的保留")}
    if tool == "flow_accept":
        step, code = args.get("step"), args.get("code")
        home = steptools._flow(root).home
        files = _stage_files(home / str(code) / "stage" / str(step))
        pd = paths.project_dir(root, str(code))
        ch, diff = file_changes(files, pd, f"projects/{code}/")
        if files.get("board.yaml"):
            ch += pin_changes(files["board.yaml"], _read(pd / "alloc" / "board.yaml"))
        return {"title": f"写入 {STEP_CN.get(step, step)}", "summary": f"项目 {code} · {len([x for x in ch if x['k'] == 'file'])} 个文件",
                "steps": [{"title": STEP_CN.get(step, step), "state": "ok", "facts": [], "changes": ch, "detail": diff}],
                "after": "写入后自动把下一步的预览备好"}
    if tool == "score_save":
        r = getattr(svc, "score_runs", {}).get(str(args.get("item"))) or {}
        runs = r.get("runs") or []
        ok = sum(1 for x in runs if x["result"].get("pass"))
        return {"title": f"保存评分项 {args.get('item')} 的证据", "summary": f"{where} · {ok}/{len(runs)} 次通过 · 规格 {r.get('spec')}",
                "steps": [{"title": f"第 {x['n']} 次", "state": "ok" if x["result"].get("pass") else "fail",
                           "facts": [x["result"].get("why") or "到位并保持"], "changes": [{"k": "file", "name": f"run_{x['n']:02d}.csv", "old": None, "new": f"{x['csv'].count(chr(10)) - 1} 行"}], "detail": ""} for x in runs],
                "after": "写到工程目录 $DZBENCH_HOME/projects/<题号>/verify/logs/ 下（每次一个 CSV + result.json）"}
    if tool == "score_writeback":
        from .. import scoring
        r = getattr(svc, "score_runs", {}).get(str(args.get("item"))) or {}
        res = r.get("result", "fail")
        args = args | {"dir": args.get("dir") or r.get("dir")}
        try:
            d = scoring.writeback(svc, {"item": str(args.get("item")), "dir": args.get("dir"), "layer": "sim" if svc.sim else "bench", "result": res, "note": args.get("note", "")})
        except Exception as e:  # noqa: BLE001
            return {"title": "回写评分结果", "error": getattr(e, "msg", str(e)), "steps": []}
        return {"title": f"回写评分项 {args.get('item')}", "summary": f"{d.get('path')} · 结果 {res}",
                "steps": [{"title": "requirements.yaml", "state": "ok" if res == "pass" else "warn", "facts": [],
                           "changes": [{"k": "evidence", "name": str(args.get("dir")), "old": None, "new": res}], "detail": d.get("diff") or ""}],
                "after": "文件在这期间被改过就拒绝写"}
    if tool in ("flash", "flash_rollback"):
        from ..flash import FlashError
        try:
            p = (svc.flasher.flash if tool == "flash" else svc.flasher.rollback)(dry_run=True)
        except FlashError as e:
            return {"title": "烧录固件" if tool == "flash" else "回滚到烧前固件", "error": e.message, "steps": []}
        pre = p.get("preconditions") or []
        img = str(p.get("image") or "")
        return {"title": "烧录固件" if tool == "flash" else "回滚到烧前固件", "summary": f"{where} · {pathlib.Path(img).name}" + (f" → {p['base']}" if p.get("base") else ""),
                "steps": [{"title": "前置检查", "state": "ok" if all(x.get("ok") for x in pre) else "fail",
                           "facts": [("✓ " if x.get("ok") else "✗ ") + str(x.get("why") or x.get("name") or "") for x in pre], "changes": [], "detail": ""},
                          {"title": "执行顺序", "state": "ok", "facts": p.get("steps") or [], "changes": [], "detail": img}],
                "after": "烧完核对心跳（schema 一致才算起来了）", "plan": p}
    if tool in svc.EXPERIMENTS:
        pa = svc.prearm()
        gains = svc._gains() if hasattr(svc, "_gains") else {}
        return {"title": {"run_step_test": "实机阶跃实验", "run_sweep_test": "实机正弦扫频", "rollback_best": "回滚到最好参数", "score_run": "跑评分项"}.get(tool, tool),
                "summary": where + (f" · 当前 {'、'.join(f'{k}={v:.4g}' for k, v in gains.items())}" if gains else ""),
                "steps": [], "prearm": pa, "error": "；".join(pa["failed"]) if pa["failed"] else None,
                "after": "执行中随时可按急停"}
    return None
