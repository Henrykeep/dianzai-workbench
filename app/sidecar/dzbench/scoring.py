"""评分页后端：读评分项、存证据。判定（到位 / 最差 N 轮）在界面里用 accept.ts 算（与 accept.py 同一定义），这里只读写文件。

评分表结构借 DS-land-and-air docs/D题_V23_联调与计分矩阵.md 的“得分验收矩阵”：
  评分项 | 工作台自动判定（accept 规格） | 人工 / 物理证据（metric.how） | 当前结论（默认“未验收”，只有现场层通过才算得分）
证据目录用 docs/verify 规范，目录由 tools/req.py newlog 建（不另写一套命名）。
"""
from __future__ import annotations

import base64
import datetime
import json
import pathlib
import re
import subprocess
import sys

import yaml


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
    c = sorted(root.glob("examples/*/requirements.yaml"))
    if not c:
        raise ScoreError("no_req", "仓库里没有 requirements.yaml", "先在项目页第 1 步读题起稿")
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
                     "evidence": it.get("evidence") or []})
    cands = [q.relative_to(root).as_posix() for q in sorted(root.glob("examples/*/requirements.yaml"))]
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
    p = subprocess.run([sys.executable, "tools/req.py", "newlog", "--root", f"docs/verify/{code}", "--task", item, "--layer", layer],
                       cwd=root, capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise ScoreError("newlog", "建证据目录失败：" + (p.stdout + p.stderr)[-300:])
    d = pathlib.Path(p.stdout.splitlines()[0].strip())
    d = d if d.is_absolute() else root / d
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
    rel = d.relative_to(root).as_posix()
    return {"dir": rel, "files": files, "evidence": f"- {{ path: {rel}, layer: {layer}, date: {datetime.date.today()}, result: {summ.get('result', 'TODO')} }}"}
