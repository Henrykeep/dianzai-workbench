"""项目页引导流程（读题 → 选型 → 导入工程 → 资源分配 → 生成）：只调仓库里现成的命令行工具，不改它们。

规则：每一步先在暂存区跑（~/.dzbench/flow/<题号>/stage/<步>/），把输出和生成的文件原样给界面看；
用户点“确认”才把（可能改过的）文件写到目标位置。没确认之前，仓库和用户原工程一个字不动。
  req     tools/req.py init <题目> -o stage/requirements.yaml            → 确认写 <题目目录>/requirements.yaml
  scheme  tools/scheme.py <req> --init-scheme stage/scheme.yaml -o stage → 确认写 <题目目录>/scheme.yaml
  import  tools/import_project.py <用户工程> --root <暂存根>              → 确认把 boards/<板>/ 拷进仓库
          （暂存根 = 仓库顶层逐项软链，boards/ 是真目录；USER CODE 修复 diff 要另点“接受修复”才带 --accept-repair 重跑）
  alloc   tools/alloc.py <题目目录>/scheme.yaml -o stage [--fixed 导入的 board.yaml] → 确认写 <题目目录>/alloc/
  gen     没有 project.yaml 就按能力标签从 tools/catalog/subsys_catalog.yaml 挑子系统、add_subsys.py 装进暂存草稿；
          tools/gen_project.py -o stage/gen；有 .uvprojx 时 keil_inject --dry-run
          → 确认写草稿（只补没有的文件）+ build/<题号>/gen/
  keil    第二次确认（confirm_uvprojx 等于要改的路径）才真跑 keil_inject（它先备份 <x>.uvprojx.bak）
"""
from __future__ import annotations

import base64
import os
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

TEXT_EXT = {".yaml", ".yml", ".md", ".txt", ".h", ".c", ".json", ".csv", ".mk", ".ld", ".sct"}


class FlowError(Exception):
    def __init__(self, code: str, msg: str, fix: str = ""):
        super().__init__(msg); self.code, self.msg, self.fix = code, msg, fix


def _safe(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name or "").strip("-")
    if not s:
        raise FlowError("bad_name", "题号 / 板名只能用字母数字和 - _", "例：2026H")
    return s


def board_name(src: pathlib.Path) -> str:
    """默认板名：工程文件夹名去掉“副本 / copy / (6)”这类复制噪声；剩不下字母数字就用 .ioc 文件名。"""
    for cand in (src.name, *(f.stem for f in sorted(src.glob("*.ioc")))):
        s = re.sub(r"副本|\bcopy\b|\(\d+\)|（\d+）", " ", cand, flags=re.I)
        s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()   # 板名规则 ^[a-z0-9][a-z0-9-]{1,47}$（schema/board），下划线也换成 -
        s = re.sub(r"-{2,}", "-", s)
        if s:
            return s
    return "board"


def board_slug(name: str) -> str:
    """用户填的板名按板卡 schema 规整：小写、非字母数字换 -。"""
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def find_uvprojx(src: pathlib.Path) -> str:
    """工程里的 Keil .uvprojx（CubeMX 一般在 MDK-ARM/ 下）；没有就空串。"""
    fs = sorted(src.glob("*.uvprojx")) + sorted(src.glob("*/*.uvprojx"))
    return str(fs[0]) if fs else ""


def _scheme_mod(repo: pathlib.Path):
    """调用（不改）tools/scheme.py 里的筛选 / 排序函数。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dz_scheme", repo / "tools" / "scheme.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def scheme_choices(repo: pathlib.Path, req: dict, scheme: dict) -> dict:
    """每个能力标签一组候选（scheme.py 的排序：仓库支持 上板 > 仿真 > 编译 > 无驱动；规则禁用的单列），给界面做单选。"""
    sc = _scheme_mod(repo); parts = sc.load_catalog(); nd, forb = sc.needs_of(req), sc.forbidden(req)
    picks = scheme.get("picks") or {}
    out = []
    for n in sorted(nd, key=lambda k: -sc.weight(nd[k])):
        ok, banned = sc.candidates(parts, n, forb)
        out.append({"need": n, "score": sc.weight(nd[n]), "items": [i["id"] for i in nd[n]], "pick": picks.get(n) or (ok[0]["id"] if ok else ""),
                    "options": [{"id": x["id"], "name": x["name"], "status": x["status"], "pros": x.get("pros", [])[:2], "cons": x.get("cons", [])[:2]} for x in ok],
                    "banned": [{"id": x["id"], "name": x["name"], "why": why} for x, why in banned]})
    mcus = sorted((p for p in parts.values() if p["kind"] == "mcu"), key=lambda p: (sc.RANK[p["status"]], p["id"]))
    return {"needs": out, "mcu": scheme.get("mcu") or "", "mcus": [{"id": x["id"], "name": x["name"], "status": x["status"]} for x in mcus]}


def apply_picks(text: str, picks: dict, reasons: dict, mcu: str | None = None) -> str:
    """把界面单选的结果写进 scheme.yaml（保留第一行注释头，其它键原样）。"""
    head = "".join(l + "\n" for l in text.splitlines() if l.startswith("#"))
    d = yaml.safe_load(text) or {}
    d.setdefault("picks", {}); d.setdefault("reasons", {})
    for k, v in (picks or {}).items():
        if v:
            d["picks"][k] = v
        else:
            d["picks"].pop(k, None)
    for k, v in (reasons or {}).items():
        if v:
            d["reasons"][k] = v
    if mcu:
        d["mcu"] = mcu
    return head + yaml.safe_dump(d, allow_unicode=True, sort_keys=False)


def subsys_plan(repo: pathlib.Path, req: dict, scheme: dict) -> dict:
    """按能力标签挑现成子系统（tools/catalog/subsys_catalog.yaml 的 serves 有交集就选），列出没人管的标签。"""
    tags = set((_scheme_mod(repo).needs_of(req)).keys()) | set((scheme.get("picks") or {}).keys())
    tags -= set(scheme.get("offboard") or [])
    cat = (yaml.safe_load((repo / "tools" / "catalog" / "subsys_catalog.yaml").read_text(encoding="utf-8")) or {}).get("subsystems") or []
    chosen, served = [], set()
    for c in cat:
        hit = sorted(tags & set(c["serves"]))
        if hit and (repo / c["path"] / "subsys.yaml").exists():
            chosen.append({"name": pathlib.Path(c["path"]).name, "path": c["path"], "tags": hit}); served |= set(hit)
    # ui.* / link.* 由 io 层直接接（不需要控制子系统），其余没人管的列出来让人用 new_subsys 新建
    missing = sorted(t for t in tags - served if not t.startswith(("ui.", "link.")))
    return {"chosen": chosen, "missing": missing}


MIN_PROJECT = """# {name}：由工作台项目页起稿（目录里没有能直接用的子系统，先留空）；子系统用 tools/new_subsys.py 新建后加进 subsystems。
schema_version: 1
name: {name}
description: TODO 一句话
boards:
  main: {board}
state:
  coord:
    owner: coord
    fields:
      - {{ name: test_id, type: uint8 }}
subsystems: []
params: []
profiles:
  - {{ name: base, desc: 默认档 }}
tests:      # TODO(用户)：按题目改
  - {{ id: 1, name: 示例, profile: base, time_limit_s: 30 }}
"""


_ALIAS = re.compile(r"^(\s*)([A-Za-z0-9_]+):(\s*)([A-Za-z0-9_]+)(\s*#\s*(.*))?$")


def alias_rows(text: str) -> list[dict]:
    """aliases.yaml → [{key, alias, note}]（note = 行尾注释里的原标签说明），只取二级缩进的 键: 值 行。"""
    rows = []
    for ln in text.splitlines():
        mm = _ALIAS.match(ln)
        if mm and mm.group(1):
            rows.append({"key": mm.group(2), "alias": mm.group(4), "note": (mm.group(6) or "").strip()})
    return rows


def apply_alias_edits(text: str, edits: dict) -> str:
    out = []
    for ln in text.splitlines():
        mm = _ALIAS.match(ln)
        if mm and mm.group(1) and mm.group(2) in edits:
            new = _safe(str(edits[mm.group(2)])).upper().replace("-", "_")
            ln = f"{mm.group(1)}{mm.group(2)}:{mm.group(3)}{new}{mm.group(5) or ''}"
        out.append(ln)
    return "\n".join(out) + "\n"


class Flow:
    def __init__(self, repo: pathlib.Path, home: pathlib.Path | None = None):
        self.repo = pathlib.Path(repo)
        self.home = pathlib.Path(home or pathlib.Path.home() / ".dzbench" / "flow")

    # ---------------------------------------------------------------- 路径
    def stage(self, code: str, step: str) -> pathlib.Path:
        d = self.home / _safe(code) / "stage" / step
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        return d

    def target(self, code: str, dest: str | None = None) -> pathlib.Path:
        p = pathlib.Path(dest).expanduser() if dest else self.repo / "examples" / _safe(code)
        if not p.is_absolute():
            p = self.repo / p
        return p

    def _run(self, args: list, cwd: pathlib.Path | None = None) -> dict:
        cmd = [sys.executable, *map(str, args)]
        p = subprocess.run(cmd, cwd=cwd or self.repo, capture_output=True, text=True, timeout=300)
        shown = " ".join(str(a) for a in args)
        return {"cmd": "python3 " + shown, "rc": p.returncode, "out": (p.stdout + p.stderr)[-20000:]}

    @staticmethod
    def _files(d: pathlib.Path) -> dict:
        out = {}
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.suffix in TEXT_EXT and f.stat().st_size < 200_000:
                out[f.relative_to(d).as_posix()] = f.read_text(encoding="utf-8", errors="replace")
        return out

    @staticmethod
    def _kargs(m: dict) -> list:
        if not (m.get("board") and m.get("app")):
            raise FlowError("need_board_app", "Keil 注入要同时选板卡和应用（按这次构建挑模块）")
        return ["--board", m["board"], "--app", m["app"]]

    # ---------------------------------------------------------------- 各步预览（只写暂存区）
    def preview(self, step: str, m: dict) -> dict:
        code = _safe(m.get("code") or "题目")
        tgt = self.target(code, m.get("dest"))
        if step == "req":
            st = self.stage(code, "req")
            if m.get("pdf_b64"):
                src = st / ("题目" + (pathlib.Path(m.get("filename") or "x.pdf").suffix or ".pdf"))
                src.write_bytes(base64.b64decode(m["pdf_b64"]))
            elif m.get("src"):
                src = pathlib.Path(m["src"]).expanduser()
            else:
                raise FlowError("no_src", "先拖入题目 PDF（或 .txt）")
            r = self._run(["tools/req.py", "init", src, "-o", st / "requirements.yaml", "--code", code])
            d = yaml.safe_load((st / "requirements.yaml").read_text(encoding="utf-8")) if (st / "requirements.yaml").exists() else {}
            return r | {"items": (d or {}).get("items") or [], "constraints": (d or {}).get("constraints") or [], "target": str(tgt / "requirements.yaml")}
        if step == "scheme":
            req = tgt / "requirements.yaml"
            if not req.exists():
                raise FlowError("no_req", f"{req} 还没有：先确认第 1 步")
            st = self.stage(code, "scheme")
            r = self._run(["tools/scheme.py", req, "--init-scheme", st / "scheme.yaml"])
            r2 = self._run(["tools/scheme.py", req, "-o", st])
            ch = None
            if (st / "scheme.yaml").exists():
                ch = scheme_choices(self.repo, yaml.safe_load(req.read_text(encoding="utf-8")) or {}, yaml.safe_load((st / "scheme.yaml").read_text(encoding="utf-8")) or {})
            return {"cmd": r["cmd"] + "\n" + r2["cmd"], "rc": r["rc"] or r2["rc"], "out": r["out"] + r2["out"], "files": self._files(st), "target": str(tgt / "scheme.yaml"), "choices": ch}
        if step == "import":
            src = pathlib.Path(m.get("project") or "").expanduser()
            if not (src.is_dir() and list(src.glob("*.ioc"))):
                raise FlowError("no_ioc", f"{src} 里没有 .ioc", "选 CubeMX 工程根目录（有 .ioc 和 Core/）")
            name = _safe(board_slug(m["name"]) if m.get("name") else board_name(src))
            st = self.stage(code, "import")
            root = st / "root"; (root / "boards").mkdir(parents=True)
            for e in self.repo.iterdir():                      # 暂存根：仓库顶层逐项软链，boards/ 另建
                if e.name not in ("boards", ".git"):
                    (root / e.name).symlink_to(e)
            for b in (self.repo / "boards").iterdir():
                if b.name != name:
                    (root / "boards" / b.name).symlink_to(b)
            if (self.repo / "boards" / name / "aliases.yaml").exists():   # 已有别名表沿用（与 --force 的行为一致）
                (root / "boards" / name).mkdir(); shutil.copy(self.repo / "boards" / name / "aliases.yaml", root / "boards" / name)
            args = ["tools/import_project.py", src, "--name", name, "--root", root, "--report", st / "report.json", "--force"]
            if m.get("accept_repair"):
                args.append("--accept-repair")
            r = self._run(args)
            bd = root / "boards" / name
            al = alias_rows((bd / "aliases.yaml").read_text(encoding="utf-8")) if (bd / "aliases.yaml").exists() else []
            need_repair = "USER CODE 标记被改坏" in r["out"] and not m.get("accept_repair")
            exists = (self.repo / "boards" / name).exists()
            return r | {"name": name, "aliases": al, "need_repair": need_repair, "files": self._files(bd) if bd.is_dir() else {},
                        "target": str(self.repo / "boards" / name), "overwrite": exists, "uvprojx": find_uvprojx(src)}
        if step == "alloc":
            sch = tgt / "scheme.yaml"
            if not sch.exists():
                raise FlowError("no_scheme", f"{sch} 还没有：先确认第 2 步")
            st = self.stage(code, "alloc")
            args = ["tools/alloc.py", sch, "-o", st]
            if m.get("board"):
                fb = self.repo / "boards" / _safe(m["board"]) / "board.yaml"
                if fb.exists():
                    args += ["--fixed", fb]
            if (tgt / "app.yaml").exists():
                args += ["--app", tgt / "app.yaml"]
            return self._run(args) | {"files": self._files(st), "target": str(tgt / "alloc")}
        if step == "gen":
            st = self.stage(code, "gen")
            pj = tgt / "project.yaml"
            out = {"cmd": "", "rc": 0, "out": "", "files": {}, "target": str(self.repo / "build" / code / "gen")}
            if not pj.exists():
                # 没有 project.yaml：按能力标签从子系统目录挑现成子系统，用 tools/add_subsys.py 装进暂存区的草稿题目
                req = yaml.safe_load((tgt / "requirements.yaml").read_text(encoding="utf-8")) if (tgt / "requirements.yaml").exists() else {"items": []}
                sch = yaml.safe_load((tgt / "scheme.yaml").read_text(encoding="utf-8")) if (tgt / "scheme.yaml").exists() else {}
                plan = subsys_plan(self.repo, req or {"items": []}, sch or {})
                dr = st / "draft" / code; dr.mkdir(parents=True)
                board = _safe(m["board"]) if m.get("board") else "main"
                logs, cmds = [], []
                for c in plan["chosen"]:
                    r = self._run(["tools/add_subsys.py", self.repo / c["path"], dr, "--board", board])
                    cmds.append(r["cmd"]); logs.append(r["out"])
                    if r["rc"]:
                        raise FlowError("add_subsys", f"装 {c['name']} 失败：" + r["out"][-400:])
                if not (dr / "project.yaml").exists():
                    (dr / "project.yaml").write_text(MIN_PROJECT.format(name=code, board=board), encoding="utf-8")
                pj = dr / "project.yaml"
                out["draft"] = plan | {"files": self._files(dr), "target": str(tgt)}
                note = ("起稿 project.yaml：" + ("、".join(f"{c['name']}（{'/'.join(c['tags'])}）" for c in plan["chosen"]) or "没有匹配的现成子系统，先留空")
                        + ("；这些能力没有现成子系统，要用 tools/new_subsys.py 新建：" + "、".join(plan["missing"]) if plan["missing"] else "") + "\n")
                out["cmd"] = "\n".join(cmds); out["out"] = note + "".join(logs)
            r = self._run(["tools/gen_project.py", pj, "-o", st / "gen"])
            out["cmd"] = (out["cmd"] + "\n" + r["cmd"]).strip(); out["rc"] = r["rc"]; out["out"] += r["out"]; out["files"] = self._files(st / "gen")
            if m.get("uvprojx"):
                uv = pathlib.Path(m["uvprojx"]).expanduser()
                r = self._run(["tools/keil_inject.py", uv, "--root", self.repo, *self._kargs(m), "--dry-run"])
                out["cmd"] += "\n" + r["cmd"]; out["out"] += "\n" + r["out"]; out["keil"] = {"rc": r["rc"], "uvprojx": str(uv), "bak": str(uv) + ".bak"}
            return out
        raise FlowError("bad_step", f"没有这一步：{step}")

    # ---------------------------------------------------------------- 确认（才真正写）
    def accept(self, step: str, m: dict) -> dict:
        code = _safe(m.get("code") or "题目")
        tgt = self.target(code, m.get("dest"))
        if step == "keil":                              # 真改用户的 .uvprojx：要第二次明确确认（把要改的路径原样回传）
            uv = pathlib.Path(m.get("uvprojx") or "").expanduser()
            if not uv.is_file():
                raise FlowError("no_uvprojx", f"{uv} 不存在")
            if m.get("confirm_uvprojx") != str(uv):
                raise FlowError("need_confirm", "真改 Keil 工程要再确认一次", f"确认要改 {uv}（备份到 {uv}.bak）")
            r = self._run(["tools/keil_inject.py", uv, "--root", self.repo, *self._kargs(m)])
            if r["rc"]:
                raise FlowError("keil_inject", "Keil 注入失败：" + r["out"][-400:])
            return {"written": [str(uv)], "bak": str(uv) + ".bak", "out": r["out"]}
        st = self.home / code / "stage" / step
        if not st.exists():
            raise FlowError("no_preview", "先点“运行”看结果，再确认")
        written: list[str] = []

        def put(p: pathlib.Path, text: str):
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8"); written.append(str(p))
        if step == "req":
            d = yaml.safe_load((st / "requirements.yaml").read_text(encoding="utf-8")) or {}
            if "items" in m:                               # 界面表格改过的评分项
                d["items"] = m["items"]
            head = f"# 由工作台项目页起稿（tools/req.py init），{len(d.get('items') or [])} 项；逐条对照原文核对\n"
            put(tgt / "requirements.yaml", head + yaml.safe_dump(d, allow_unicode=True, sort_keys=False))
        elif step == "scheme":
            text = m.get("scheme_yaml") or (st / "scheme.yaml").read_text(encoding="utf-8")
            if m.get("picks") or m.get("mcu"):
                text = apply_picks(text, m.get("picks") or {}, m.get("reasons") or {}, m.get("mcu"))
            put(tgt / "scheme.yaml", text)
            for f in ("options.md", "scheme.md"):
                if (st / f).exists():
                    put(tgt / "scheme" / f, (st / f).read_text(encoding="utf-8"))
        elif step == "import":
            name = _safe(m["name"]); src = st / "root" / "boards" / name
            if not (src / "board.yaml").exists():
                raise FlowError("import_failed", "暂存区里没有导入成功的板卡，看上面的输出")
            dst = self.repo / "boards" / name
            if dst.exists() and not m.get("overwrite"):
                raise FlowError("exists", f"boards/{name}/ 已存在", "勾“覆盖已有板卡”再确认（别名表会保留你改过的）")
            if m.get("alias_edits"):                       # 只改别名本身，注释（原标签）原样留着
                p = src / "aliases.yaml"; p.write_text(apply_alias_edits(p.read_text(encoding="utf-8"), m["alias_edits"]), encoding="utf-8")
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=False); written.append(str(dst))
        elif step == "alloc":
            for rel, text in self._files(st).items():
                put(tgt / "alloc" / rel, text)
        elif step == "gen":
            dr = st / "draft" / code
            if dr.is_dir():                                 # 草稿题目：只补没有的文件，不覆盖题目目录里已有的
                for f in sorted(dr.rglob("*")):
                    rel = f.relative_to(dr)
                    if f.is_file() and f.suffix != ".bak" and not (tgt / rel).exists():
                        (tgt / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(f, tgt / rel); written.append(str(tgt / rel))
            for rel, text in self._files(st / "gen").items() if (st / "gen").exists() else []:
                put(self.repo / "build" / code / "gen" / rel, text)
        else:
            raise FlowError("bad_step", f"没有这一步：{step}")
        return {"written": written}
