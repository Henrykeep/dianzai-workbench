"""Agent 的“项目 / 评分”工具：只是把工作台已有入口（projflow.Flow、scoring）包成工具，不另起一套逻辑。

- project_state  只读：examples/<code>/ 下项目流程走到哪一步、评分项有几条已有证据（Agent 的“项目状态”依据）
- flow_preview   只写暂存区（~/.dzbench/flow），等同项目页“运行”（op flow_preview）
- flow_accept    真正写仓库 → 风险 human，变成确认卡，等同项目页“确认写入”（op flow_accept）
- score_items    只读：评分项和已有证据，等同评分页列表（op score_items）
数字一律来自文件，这里不推断。
"""
from __future__ import annotations

import pathlib

import yaml

from .gateway import GatewayError

STEPS = ("req", "scheme", "import", "alloc", "gen")
LABEL = {"req": "① 读题", "scheme": "② 方案", "import": "③ 导入工程", "alloc": "④ 资源分配", "gen": "⑤ 生成工程"}
NEEDS = {"req": "src（题目 PDF/txt 路径）", "import": "project（CubeMX 工程根目录，含 .ioc）；没有工程就用 mcu 从零新建（flow_preview step=scratch 先列选项）"}


def _yaml(p: pathlib.Path) -> dict:
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001  坏 yaml 当没有，状态里如实写
        return {}


def own_board(root: pathlib.Path, code: str) -> dict:
    """这个项目自己的板：project.yaml 的 boards.main（导入/选定过）> alloc/board.yaml 的 name（从零新建的草稿）。"""
    d = pathlib.Path(root) / "examples" / code
    pj = _yaml(d / "project.yaml")
    main = (pj.get("boards") or {}).get("main") if isinstance(pj.get("boards"), dict) else None
    draft = _yaml(d / "alloc" / "board.yaml").get("name")
    out = {"declared": main, "draft": draft, "exists": bool(main and (pathlib.Path(root) / "boards" / main / "board.yaml").exists())}
    if draft:                                   # 从零新建分支：.ioc 写到 ~/dz-cubemx/<name>/，人在 CubeMX 点 GENERATE 后才有 main.c
        cm = pathlib.Path.home() / "dz-cubemx" / draft
        out |= {"ioc_written": (cm / f"{draft}.ioc").exists(), "cubemx_generated": (cm / "Core" / "Src" / "main.c").exists(), "cubemx_dir": str(cm)}
    return out


def project_state(root: pathlib.Path, code: str | None = None) -> dict:
    root = pathlib.Path(root)
    codes = sorted(p.name for p in (root / "examples").iterdir() if p.is_dir()) if (root / "examples").is_dir() else []
    boards = sorted(p.name for p in (root / "boards").iterdir() if (p / "board.yaml").exists()) if (root / "boards").is_dir() else []
    if not code:
        return {"projects": codes, "boards": boards, "hint": "指定 code 看某个项目走到哪一步"}
    d = root / "examples" / code
    req = _yaml(d / "requirements.yaml")
    items = req.get("items") or []
    ob = own_board(root, code)
    hw = ob["exists"] or bool(ob.get("ioc_written"))            # 导入了自己的板，或从零新建已写出 .ioc
    done = {"req": bool(items), "scheme": (d / "scheme.yaml").exists(), "import": hw,
            "alloc": (d / "alloc").is_dir() and any((d / "alloc").iterdir()), "gen": (root / "build" / code / "gen").is_dir()}
    nxt = next((s for s in STEPS if not done[s]), None)
    return {"code": code, "steps": {LABEL[s]: done[s] for s in STEPS}, "next_step": nxt, "next_needs": NEEDS.get(nxt or "", ""),
            "board": ob, "req_items": len(items), "items_with_evidence": sum(bool(i.get("evidence")) for i in items),
            "has_project_yaml": (d / "project.yaml").exists(), "boards": boards,
            "human_todo": ("在 CubeMX 打开 " + ob["cubemx_dir"] + " 里的 .ioc 点一次 GENERATE CODE") if ob.get("ioc_written") and not ob.get("cubemx_generated") else ""}


def _flow(root):
    from ..projflow import Flow
    return Flow(root)


def _err(e) -> GatewayError:
    return GatewayError(e.code, e.msg, e.fix)


def _brief(r: dict) -> dict:
    """暂存结果给模型看的摘要：文件只给名字和行数（全文在项目页里），输出只留尾巴。"""
    out = {k: r[k] for k in ("rc", "target", "need_repair", "overwrite", "name", "uvprojx", "keil") if k in r}
    out["out_tail"] = (r.get("out") or "")[-1500:]
    if "files" in r:
        out["files"] = {f: t.count("\n") + 1 for f, t in r["files"].items()}
    if "items" in r:
        out["items"] = [{"id": i.get("id"), "score": i.get("score"), "text": str(i.get("text", ""))[:60]} for i in r["items"]]
    if "aliases" in r:
        out["aliases"] = r["aliases"]
    return out


def flow_preview(root, step: str, code: str, **m) -> dict:
    from ..projflow import FlowError
    try:
        return _brief(_flow(root).preview(step, {"code": code, **m}))
    except FlowError as e:
        raise _err(e) from None


def flow_accept(root, step: str, code: str, **m) -> dict:
    from ..projflow import FlowError
    try:
        return _flow(root).accept(step, {"code": code, **m})
    except FlowError as e:
        raise _err(e) from None


def score_items(svc, path: str | None = None) -> dict:
    from .. import scoring
    try:
        r = scoring.items(svc, {"path": path} if path else {})
    except scoring.ScoreError as e:
        raise _err(e) from None
    return {"path": r["path"], "code": r["code"], "n": len(r["items"]),
            "items": [{"id": i["id"], "score": i["score"], "text": i["text"][:60], "metrics": i["metrics"],
                       "evidence": len(i["evidence"])} for i in r["items"]]}


# ---------------------------------------------------------------- 一句话跑完项目流程
def project_chain(root, code: str, src: str | None = None, project: str | None = None, name: str | None = None,
                  mcu: str | None = None, tpl: str | None = None, uvprojx: str | None = None, app: str | None = None, hand_edit: str | None = None) -> dict:
    """把还没做的步依次预览完（全部落在暂存区 + 沙盒题目目录，不动仓库），返回一张“批量写入”清单给 project_apply。
    后一步要读前一步的结果：前一步在沙盒目录里 accept（Flow 的 dest 参数），所以真仓库一个字节都不变。
    gen 的 accept 会写仓库 build/，所以只预览不在沙盒确认；import 会写 boards/，同理。"""
    import shutil
    from ..projflow import FlowError, scratch_options
    root = pathlib.Path(root); f = _flow(root)
    if src and not pathlib.Path(src).is_absolute() and (root / src).exists():
        src = str(root / src)            # 模型只知道仓库相对路径
    real = root / "examples" / code
    sb = f.home / code / "sandbox"
    if sb.exists():
        shutil.rmtree(sb)
    if real.is_dir():
        shutil.copytree(real, sb)
    else:
        sb.mkdir(parents=True)
    st = project_state(root, code)
    todo = [s for s in STEPS if not st["steps"][LABEL[s]]]
    m0 = {"code": code, "dest": str(sb)}
    steps, batch = [], []
    board = st["board"].get("declared")

    def stop(step, why, fix=""):
        steps.append({"step": step, "ok": False, "why": why, "fix": fix})
        return {"code": code, "steps": steps, "batch": batch, "stopped_at": step}
    try:
        if "req" in todo:
            if not src:
                return stop("req", "缺题目文件", "把题目 PDF/txt 的路径发我")
            r = f.preview("req", m0 | {"src": src})
            if r["rc"] or not r.get("items"):
                return stop("req", "读题没拆出评分项：" + (r.get("out") or "")[-300:])
            f.accept("req", m0)
            steps.append({"step": "req", "ok": True, "items": len(r["items"]), "first": [str(i.get("text", ""))[:40] for i in r["items"][:3]]})
            batch.append(("req", {}))
        if "scheme" in todo:
            r = f.preview("scheme", m0)
            if r["rc"]:
                return stop("scheme", "方案起稿失败：" + r["out"][-300:])
            f.accept("scheme", m0)
            sch = _yaml(sb / "scheme.yaml")
            steps.append({"step": "scheme", "ok": True, "mcu": sch.get("mcu"), "files": list(r["files"])})
            batch.append(("scheme", {}))
        if "import" in todo:
            if project:
                r = f.preview("import", {"code": code, "project": project} | ({"name": name} if name else {}))
                if r["rc"] and not r.get("need_repair"):
                    return stop("import", "导入失败：" + r["out"][-300:])
                if r.get("need_repair"):
                    return stop("import", "main.c 的 USER CODE 标记坏了，要先看修复对比", "到项目页③看修复前后的对比，确认后再让我继续")
                board = r["name"]
                steps.append({"step": "import", "ok": True, "board": board, "aliases": len(r.get("aliases") or []), "overwrite": r.get("overwrite")})
                if r.get("overwrite"):
                    return stop("import", f"boards/{board} 已存在，批量写入不覆盖", "换个板名（name），或在项目页③勾“覆盖”")
                batch.append(("import", {"name": board}))
            else:                                   # 没有工程：从零新建，芯片按方案/候选排序取第一个能生成 .ioc 的
                opts = scratch_options(root, _yaml(sb / "scheme.yaml"))
                o = next((x for x in opts if x["ok"] and (not mcu or x["mcu"] == mcu) and (tpl is None or x["tpl"] == tpl)), None)
                if not o:
                    return stop("scratch", "没有能生成 .ioc 的芯片候选" + (f"（{mcu}）" if mcu else ""), "给我 CubeMX 工程路径走导入")
                r = f.preview("scratch", m0 | {"mcu": o["mcu"], "tpl": o["tpl"]} | ({"name": name} if name else {}))
                if r["rc"]:
                    return stop("scratch", "从零新建失败：" + r["out"][-300:])
                board = r["name"]
                steps.append({"step": "scratch", "ok": True, "mcu": o["mcu"], "label": o["label"], "board": board, "ioc": r["ioc"],
                              "others": [x["label"] for x in opts if x["ok"] and x is not o][:3]})
                batch.append(("scratch", {"name": board}))
                f.accept("scratch", m0 | {"name": board, "cubemx_dir": str(sb / "_cubemx" / board)})   # 让后面的步看到 alloc/（.ioc 落沙盒）
        if "alloc" in todo and not (sb / "alloc").is_dir():
            r = f.preview("alloc", m0 | ({"board": board} if board else {}))
            if r["rc"]:
                return stop("alloc", "资源分配失败：" + r["out"][-300:])
            f.accept("alloc", m0)
            steps.append({"step": "alloc", "ok": True, "files": list(r["files"])})
            batch.append(("alloc", {}))
        if "gen" in todo:
            r = f.preview("gen", m0 | ({"board": board} if board else {}))      # 不传板名 project.yaml 会写成 main，导入状态就丢了
            d = r.get("draft") or {}
            steps.append({"step": "gen", "ok": not r["rc"], "rc": r["rc"], "files": len(r.get("files") or {}),
                          "subsys": [c["name"] for c in d.get("chosen") or []], "missing": d.get("missing") or [], "out_tail": r["out"][-400:]})
            if r["rc"]:
                return {"code": code, "steps": steps, "batch": batch, "stopped_at": "gen"}
            batch.append(("gen", {}))
        # ⑤ 之后：有 Keil 工程就把工作台模块注入 .uvprojx（同一张卡里一起确认；导入的工程自动找 MDK-ARM/*.uvprojx）
        from ..projflow import find_uvprojx
        uv = uvprojx or (find_uvprojx(pathlib.Path(project).expanduser()) if project else "")
        if uv and board and (project or (root / "boards" / board).is_dir()):   # 从零新建要先在 CubeMX 生成+导入才有板，此时不注入
            km = {"code": code, "board": board, "app": app or code, "uvprojx": str(pathlib.Path(uv).expanduser())}
            from ..projflow import keil_hand_edited
            if keil_hand_edited(pathlib.Path(km["uvprojx"])) and hand_edit not in ("merge", "keep"):
                return stop("keil", "检测到 dz/ 组在上次注入后被手改过",
                            "选“合并”（hand_edit=merge：重写 dz/ 组，备份 .bak）或“保留”（hand_edit=keep：这次不注入）")
            if hand_edit:
                km["hand_edit"] = hand_edit
            if (root / "apps" / km["app"]).is_dir() or (root / "examples" / km["app"] / "project.yaml").exists():
                r = f._run(["tools/keil_inject.py", km["uvprojx"], "--root", f.repo, *f._kargs(km), "--dry-run"])
            else:                                   # 应用要等 ⑤ 写入后才有：预演留到写入时按顺序跑（失败就停在这步）
                r = {"rc": 0, "out": "⑤ 写入后再注入（应用此刻还在暂存区）"}
            steps.append({"step": "keil", "ok": not r["rc"], "uvprojx": km["uvprojx"], "out_tail": r["out"][-400:],
                          **({} if not r["rc"] else {"why": "Keil 注入预演失败", "fix": r["out"][-200:]})})
            if r["rc"]:
                return {"code": code, "steps": steps, "batch": batch, "stopped_at": "keil"}
            batch.append(("keil", km | {"confirm_uvprojx": km["uvprojx"]}))    # 用户点的那张总卡就是“第二次确认”
    except FlowError as e:
        return stop(steps[-1]["step"] if steps else "?", e.msg, e.fix)
    return {"code": code, "steps": steps, "batch": batch, "stopped_at": None}


def project_apply(root, code: str, batch: list) -> dict:
    """把 project_chain 预览过的步按顺序真正写入（每步就是项目页那一步的“确认写入”）。任一步失败就停，前面已写的保留并报告。"""
    f = _flow(root); out = []
    for step, extra in batch:
        try:
            r = f.accept(step, {"code": code, **extra})
        except Exception as e:  # noqa: BLE001
            return {"written": out, "failed": step, "error": getattr(e, "msg", str(e))}
        out.append({"step": step, "written": r.get("written")})
    return {"written": out, "state": project_state(root, code)}
