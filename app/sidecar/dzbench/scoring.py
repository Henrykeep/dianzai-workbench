"""评分页后端：读评分项、存证据。判定（到位 / 最差 N 轮）在界面里用 accept.ts 算（与 accept.py 同一定义），这里只读写文件。

评分表结构借 DS-land-and-air docs/D题_V23_联调与计分矩阵.md 的“得分验收矩阵”：
  评分项 | 工作台自动判定（accept 规格） | 人工 / 物理证据（metric.how） | 当前结论（默认“未验收”，只有现场层通过才算得分）
证据目录用 docs/verify 规范（落在工程目录 verify/ 下，不进仓库），目录由 tools/req.py newlog 建（不另写一套命名）。
"""
from __future__ import annotations

import base64
import datetime
import json
import pathlib
import re
import subprocess
import os
import sys

import yaml

from . import paths


class ScoreError(Exception):
    def __init__(self, code: str, msg: str, fix: str = ""):
        super().__init__(msg); self.code, self.msg, self.fix = code, msg, fix


def _find_req(svc, m: dict) -> pathlib.Path:
    root = pathlib.Path(svc.gw.root)
    if m.get("path"):
        p = pathlib.Path(m["path"]).expanduser()
        return p if p.is_absolute() else root / p
    try:                                                    # 板上这组参数所在的 app.yaml 旁边
        p = root / pathlib.Path(svc.yaml_target()).parent / "requirements.yaml"
        if p.exists():
            return p
    except Exception:  # noqa: BLE001  没连板 / 没识别参数表：退到仓库里找
        pass
    c = [d / "requirements.yaml" for d in paths.project_dirs(root) if (d / "requirements.yaml").exists()]
    if not c:
        raise ScoreError("no_req", "工程目录和内置例题里都没有 requirements.yaml", "先在项目页第 1 步读题起稿")
    return c[0]


def items(svc, m: dict) -> dict:
    p = _find_req(svc, m)
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    root = pathlib.Path(svc.gw.root)
    rows = []
    for it in d.get("items") or []:
        ms = it.get("metrics") or []
        rows.append({"id": str(it.get("id")), "part": it.get("part"), "score": it.get("score"), "text": it.get("text", ""),
                     "metrics": [{k: x.get(k) for k in ("name", "op", "value", "unit", "how", "accept", "test_id")} for x in ms],
                     "evidence": it.get("evidence") or [], "accept": it.get("accept"), "runs": it.get("runs")})
    cands = [(q.relative_to(root).as_posix() if q.is_relative_to(root) else str(q))
             for q in (d / "requirements.yaml" for d in paths.project_dirs(root)) if q.exists()]
    return {"path": p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p),
            "code": str((d.get("problem") or {}).get("code") or p.parent.name), "items": rows, "candidates": cands}


def save(svc, m: dict) -> dict:
    """m = {code, item, layer, runs:[{n, csv, png_b64?, result}], summary}：建证据目录、存每轮 CSV / 曲线截图、result.json。"""
    root = pathlib.Path(svc.gw.root)
    code, item, layer = str(m["code"]), str(m["item"]), m.get("layer", "bench")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", code + item):
        raise ScoreError("bad_id", "题号 / 评分项编号只能是字母数字")
    if layer not in ("unit", "sim", "bench", "field"):
        raise ScoreError("bad_layer", "层只能是 unit / sim / bench / field")
    paths.fork(root, code)                                  # 内置例题只读：先复制到工程根目录，证据和写回都落在那里
    p = subprocess.run([os.environ.get("DZBENCH_PYTHON") or sys.executable, "tools/req.py", "newlog", "--root", str(paths.projects_dir() / code / "verify"), "--task", item, "--layer", layer],
                       cwd=root, capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise ScoreError("newlog", "建证据目录失败：" + (p.stdout + p.stderr)[-300:])
    d = pathlib.Path(p.stdout.splitlines()[0].strip())
    d = d if d.is_absolute() else root / d
    assert paths.is_writable(d), d                        # 证据只写工程根目录（#29），不进仓库 docs/
    files = []
    for r in m.get("runs") or []:
        n = int(r["n"])
        (d / f"run_{n:02d}.csv").write_text(r["csv"], encoding="utf-8"); files.append(f"run_{n:02d}.csv")
        if r.get("png_b64"):
            (d / f"run_{n:02d}.png").write_bytes(base64.b64decode(r["png_b64"].split(",")[-1])); files.append(f"run_{n:02d}.png")
    summ = m.get("summary") or {}
    (d / "result.json").write_text(json.dumps({"item": item, "layer": layer, "saved": datetime.datetime.now().isoformat(timespec="seconds"),
                                               "summary": summ, "runs": [{k: v for k, v in r.items() if k not in ("csv", "png_b64")} for r in m.get("runs") or []]},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    files.append("result.json")
    with (d / "notes.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## 工作台评分页自动记录\n- 层：{layer}；共 {len(m.get('runs') or [])} 轮；结论：{summ.get('verdict', '未判定')}\n"
                f"- 最差一轮：{summ.get('worst', '—')}\n- 文件：{'、'.join(files)}\n- 注意：只有 field（现场）层通过才能说已得分。\n")
    rel = d.relative_to(paths.projects_dir() / code).as_posix()      # 相对工程目录（requirements.yaml 所在）
    return {"dir": str(d), "files": files, "evidence": f"- {{ path: {rel}, layer: {layer}, date: {datetime.date.today()}, result: {summ.get('result', 'TODO')} }}"}


# ── 写回 requirements.yaml：只在该评分项的 evidence 列表末尾加一行（按行插入，保留注释和原排版），先给 diff，确认才写 ──
def _insert_evidence(text: str, item: str, line: str) -> str:
    ls = text.split("\n")
    head = re.compile(r"^(\s*)- id:\s*['\"]?" + re.escape(item) + r"['\"]?\s*(#.*)?$")
    i = next((k for k, s in enumerate(ls) if head.match(s)), None)
    if i is None:
        raise ScoreError("no_item", f"requirements.yaml 里没有评分项 {item}")
    ind = len(head.match(ls[i]).group(1)); kin = " " * (ind + 2)
    ind_of = lambda s: len(s) - len(s.lstrip(" "))
    end = next((k for k in range(i + 1, len(ls)) if ls[k].strip() and not ls[k].lstrip().startswith("#") and ind_of(ls[k]) <= ind), len(ls))
    while end > i + 1 and not ls[end - 1].strip():
        end -= 1
    ev = next((k for k in range(i + 1, end) if re.match(rf"^{kin}evidence:", ls[k])), None)
    entry = f"{kin}  - {line}"
    if ev is None:
        ls[end:end] = [f"{kin}evidence:", entry]
    elif re.match(rf"^{kin}evidence:\s*\[\s*\]\s*(#.*)?$", ls[ev]):
        ls[ev:ev + 1] = [f"{kin}evidence:", entry]
    else:
        last = ev
        for k in range(ev + 1, end):
            if ls[k].strip() and ind_of(ls[k]) > len(kin):
                last = k
            elif ls[k].strip() and not ls[k].lstrip().startswith("#"):
                break
        ls[last + 1:last + 1] = [entry]
    return "\n".join(ls)


def writeback(svc, m: dict) -> dict:
    """m = {path?, item, dir, layer, result: pass|fail|partial, note, confirm?, sha?}。不带 confirm 只返回 diff；带 confirm 且文件没被改过才写。"""
    import difflib, hashlib, os
    p = _find_req(svc, m); root = pathlib.Path(svc.gw.root)
    if m.get("result") not in ("pass", "fail", "partial"):
        raise ScoreError("bad_result", "result 只能是 pass / fail / partial")
    if m.get("layer") not in ("unit", "sim", "bench", "field"):
        raise ScoreError("bad_layer", "层只能是 unit / sim / bench / field")
    d = pathlib.Path(m["dir"]); d = d if d.is_absolute() else p.parent / d
    if not paths.is_writable(p):                                # 内置例题只读：写回落到工程根目录的同名工程（第一次先整份复制）
        wp = paths.projects_dir() / p.parent.name / p.name
        if not wp.exists():
            import shutil
            wp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, wp)
        p = wp
    if not d.is_dir():
        raise ScoreError("no_dir", f"证据目录 {d} 不存在", "先点“保存证据”")
    old = p.read_text(encoding="utf-8"); sha = hashlib.sha1(old.encode()).hexdigest()[:12]
    rel = os.path.relpath(d, p.parent).replace(os.sep, "/")
    q = lambda s: json.dumps(str(s), ensure_ascii=False)
    line = f"{{ path: {rel}, layer: {m['layer']}, date: {q(datetime.date.today())}, result: {m['result']}" + (f", note: {q(m['note'])}" if m.get("note") else "") + " }"
    new = _insert_evidence(old, str(m["item"]), line)
    doc = yaml.safe_load(new)                                   # 插完必须还是合法 yaml，且这一项多了这一条
    it = next(x for x in doc["items"] if str(x.get("id")) == str(m["item"]))
    if not it.get("evidence") or it["evidence"][-1].get("path") != rel:
        raise ScoreError("insert", "插入位置没认出来（排版太特别），请手动贴：" + line)
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), p.name, p.name + "（写回后）", n=2))
    out = {"path": p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p), "diff": diff, "sha": sha}
    if m.get("confirm"):
        if m.get("sha") != sha:
            raise ScoreError("changed", "requirements.yaml 在预览之后被改过", "重新预览再确认")
        p.write_text(new, encoding="utf-8"); out["written"] = True
    return out
