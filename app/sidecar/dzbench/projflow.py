"""项目页引导流程（读题 → 选型 → 导入工程 → 资源分配 → 生成）：只调仓库里现成的命令行工具，不改它们。

规则：每一步先在暂存区跑（~/.dzbench/flow/<题号>/stage/<步>/），把输出和生成的文件原样给界面看；
用户点“确认”才把（可能改过的）文件写到目标位置。没确认之前，仓库和用户原工程一个字不动。
  req     tools/req.py init <题目> -o stage/requirements.yaml            → 确认写 <题目目录>/requirements.yaml
  scheme  tools/scheme.py <req> --init-scheme stage/scheme.yaml -o stage → 确认写 <题目目录>/scheme.yaml
  import  tools/import_project.py <用户工程> --root <暂存根>              → 确认把 boards/<板>/ 拷进仓库
          （暂存根 = 仓库顶层逐项软链，boards/ 是真目录；USER CODE 修复 diff 要另点“接受修复”才带 --accept-repair 重跑）
  alloc   tools/alloc.py <题目目录>/scheme.yaml -o stage [--fixed 导入的 board.yaml] → 确认写 <题目目录>/alloc/
  gen     tools/gen_project.py <题目目录>/project.yaml -o stage/gen；有 .uvprojx 时 keil_inject --dry-run
          → 确认写 build/<题号>/gen/、keil_inject 真跑（它自己先备份 .uvprojx.bak）
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
            return {"cmd": r["cmd"] + "\n" + r2["cmd"], "rc": r["rc"] or r2["rc"], "out": r["out"] + r2["out"], "files": self._files(st), "target": str(tgt / "scheme.yaml")}
        if step == "import":
            src = pathlib.Path(m.get("project") or "").expanduser()
            if not (src.is_dir() and list(src.glob("*.ioc"))):
                raise FlowError("no_ioc", f"{src} 里没有 .ioc", "选 CubeMX 工程根目录（有 .ioc 和 Core/）")
            name = _safe(m.get("name") or src.name.lower())
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
                        "target": str(self.repo / "boards" / name), "overwrite": exists}
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
            if pj.exists():
                r = self._run(["tools/gen_project.py", pj, "-o", st / "gen"])
                out.update(cmd=r["cmd"], rc=r["rc"], out=r["out"], files=self._files(st / "gen"))
            else:
                out["out"] = f"{pj} 还没有：project.yaml（子系统 / 共享状态）由 tools/new_subsys.py 起稿，见 docs/07。\n"
                out["rc"] = 1
            if m.get("uvprojx"):
                uv = pathlib.Path(m["uvprojx"]).expanduser()
                r = self._run(["tools/keil_inject.py", uv, "--root", self.repo, *self._kargs(m), "--dry-run"])
                out["cmd"] += "\n" + r["cmd"]; out["out"] += "\n" + r["out"]; out["keil"] = {"rc": r["rc"], "uvprojx": str(uv)}
            return out
        raise FlowError("bad_step", f"没有这一步：{step}")

    # ---------------------------------------------------------------- 确认（才真正写）
    def accept(self, step: str, m: dict) -> dict:
        code = _safe(m.get("code") or "题目")
        tgt = self.target(code, m.get("dest"))
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
            put(tgt / "scheme.yaml", m.get("scheme_yaml") or (st / "scheme.yaml").read_text(encoding="utf-8"))
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
            for rel, text in self._files(st / "gen").items() if (st / "gen").exists() else []:
                put(self.repo / "build" / code / "gen" / rel, text)
            if m.get("uvprojx"):
                r = self._run(["tools/keil_inject.py", pathlib.Path(m["uvprojx"]).expanduser(), "--root", self.repo, *self._kargs(m)])
                if r["rc"]:
                    raise FlowError("keil_inject", "Keil 注入失败：" + r["out"][-400:])
                written.append(m["uvprojx"] + "（原文件已备份 .uvprojx.bak）")
        else:
            raise FlowError("bad_step", f"没有这一步：{step}")
        return {"written": written}
