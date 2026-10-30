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
NEEDS = {"req": "src（题目 PDF/txt 路径）", "import": "project（CubeMX 工程根目录，含 .ioc）"}


def _yaml(p: pathlib.Path) -> dict:
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001  坏 yaml 当没有，状态里如实写
        return {}


def project_state(root: pathlib.Path, code: str | None = None) -> dict:
    root = pathlib.Path(root)
    codes = sorted(p.name for p in (root / "examples").iterdir() if p.is_dir()) if (root / "examples").is_dir() else []
    boards = sorted(p.name for p in (root / "boards").iterdir() if (p / "board.yaml").exists()) if (root / "boards").is_dir() else []
    if not code:
        return {"projects": codes, "boards": boards, "hint": "指定 code 看某个项目走到哪一步"}
    d = root / "examples" / code
    req = _yaml(d / "requirements.yaml")
    items = req.get("items") or []
    done = {"req": bool(items), "scheme": (d / "scheme.yaml").exists(), "import": bool(boards),
            "alloc": (d / "alloc").is_dir() and any((d / "alloc").iterdir()), "gen": (root / "build" / code / "gen").is_dir()}
    nxt = next((s for s in STEPS if not done[s]), None)
    return {"code": code, "steps": {LABEL[s]: done[s] for s in STEPS}, "next_step": nxt, "next_needs": NEEDS.get(nxt or "", ""),
            "req_items": len(items), "items_with_evidence": sum(bool(i.get("evidence")) for i in items),
            "has_project_yaml": (d / "project.yaml").exists(), "boards": boards}


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
