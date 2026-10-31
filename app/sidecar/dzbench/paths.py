"""写盘位置的唯一出处（#29）。

- 用户工程：$DZBENCH_HOME/projects/<名称>/（projects_dir）。仓库 examples/ 只读：内置例题，只读不写。
- 用户板卡：$DZ_BOARDS_DIR/<板>/（未设时 = $DZBENCH_HOME/boards）。仓库 boards/ 只读：内置板卡。
- 查找顺序：用户目录优先，其次仓库内置；新建 / 写入一律落在用户目录。
- 旧版本把用户工程写在仓库 examples/ 下：migrate_plan / migrate_copy 只复制（不删、不改仓库），且要界面确认。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

from . import snapshots


def projects_dir() -> pathlib.Path:
    return snapshots.base_dir() / "projects"


def boards_dir() -> pathlib.Path:
    v = os.environ.get("DZ_BOARDS_DIR")
    return pathlib.Path(v).expanduser() if v else snapshots.base_dir() / "boards"


def project_dir(root, code: str) -> pathlib.Path:
    """已有工程：用户目录优先，其次仓库内置 examples/（只读）；都没有 = 用户目录（新建落点）。"""
    u = projects_dir() / code
    if u.is_dir():
        return u
    ex = pathlib.Path(root) / "examples" / code
    return ex if ex.is_dir() else u


def board_dir(root, name: str) -> pathlib.Path:
    u = boards_dir() / name
    if u.is_dir():
        return u
    b = pathlib.Path(root) / "boards" / name
    return b if b.is_dir() else u


def fork(root, code: str) -> pathlib.Path:
    """要写某个工程：工程根目录里还没有、仓库里有同名内置例题 → 先整份复制过来（仓库那份不动）。返回写入目录。"""
    dst = projects_dir() / code
    ex = pathlib.Path(root) / "examples" / code
    if not dst.exists() and ex.is_dir():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ex, dst, symlinks=True)
    return dst


def project_dirs(root) -> list[pathlib.Path]:
    """所有工程目录（同名时用户目录覆盖内置）。"""
    seen: dict[str, pathlib.Path] = {}
    for base in (pathlib.Path(root) / "examples", projects_dir()):
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    seen[d.name] = d
    return [seen[k] for k in sorted(seen)]


def board_dirs(root) -> list[pathlib.Path]:
    seen: dict[str, pathlib.Path] = {}
    for base in (pathlib.Path(root) / "boards", boards_dir()):
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if (d / "board.yaml").exists():
                    seen[d.name] = d
    return [seen[k] for k in sorted(seen)]


def is_writable(p) -> bool:
    """写盘白名单：只认工程根目录（projects_dir）和 DZ_BOARDS_DIR。"""
    p = pathlib.Path(p).expanduser().resolve()
    for base in (projects_dir(), boards_dir()):
        try:
            p.relative_to(base.expanduser().resolve())
            return True
        except ValueError:
            pass
    return False


def _tracked(root: pathlib.Path) -> set[str] | None:
    try:
        r = subprocess.run(["git", "ls-files", "-z", "examples"], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return {f.split("/")[1] for f in r.stdout.split("\0") if f.count("/") >= 2}


def migrate_plan(root) -> list[dict]:
    """旧版写在仓库 examples/ 下的用户工程（不受 git 管理的目录）→ 复制计划。只读，不动盘。"""
    root = pathlib.Path(root)
    ex = root / "examples"
    tracked = _tracked(root)
    if not ex.is_dir() or tracked is None:
        return []
    out = []
    for d in sorted(ex.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and d.name not in tracked:
            dst = projects_dir() / d.name
            out.append({"code": d.name, "src": str(d), "dst": str(dst), "exists": dst.exists()})
    return out


def migrate_copy(root, codes: list[str], confirmed: bool) -> dict:
    """按 migrate_plan 复制（只复制、不删源、不覆盖已有）。confirmed 必须由界面确认后带上。"""
    if not confirmed:
        return {"ok": False, "reason": "confirm_required", "message_zh": "迁移旧工程需要在界面上确认后再执行。"}
    plan = {p["code"]: p for p in migrate_plan(root)}
    done, skipped = [], []
    for c in codes:
        p = plan.get(c)
        if not p or p["exists"]:
            skipped.append(c)
            continue
        dst = pathlib.Path(p["dst"])
        assert is_writable(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(p["src"], dst, symlinks=True)
        done.append(c)
    return {"ok": True, "copied": done, "skipped": skipped}
