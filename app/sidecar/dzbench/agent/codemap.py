"""仓库地图（aider repo map 的做法）：每个代码文件的顶层定义 + 按“谁引用谁”排名，给 Agent 一页纸看懂仓库。

方法来源：github.com/Aider-AI/aider@5dc9490 aider/repomap.py（Apache-2.0）——定义/引用标签、文件为节点的引用图、
个性化 PageRank、权重规则（提到的标识符 ×10、长的 snake/camel 名 ×10、下划线开头 ×0.1、定义处 >5 个 ×0.1、
引用次数开根号）。改动：不用 tree-sitter/networkx（侧车不加依赖），定义用 Python ast + C/TS 正则抽取，
PageRank 自己迭代；缓存按 git HEAD + 工作区改动的哈希存 ~/.dzbench/codemap/。
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import pathlib
import re
import subprocess
from collections import Counter, defaultdict

from .. import snapshots

EXT = {".py", ".c", ".h", ".ts"}
SKIP = ("third_party/", "build/", "node_modules/", "app/ui/dist/", "fixtures/")
IDENT = re.compile(r"\b[A-Za-z_]\w{2,}\b")
C_DEF = re.compile(r"^(?!\s)(?:static\s+|inline\s+|extern\s+|const\s+)*[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:\{|;)?\s*$")
C_TYPE = re.compile(r"^\s*typedef\b.*\}\s*([A-Za-z_]\w*)\s*;|^\s*typedef\b[^;{(]*\b([A-Za-z_]\w*)\s*;|^\s*(?:typedef\s+)?(?:struct|enum|union)\s+([A-Za-z_]\w*)|^\}\s*([A-Za-z_]\w*)\s*;|^#define\s+([A-Za-z_]\w*(?<!_H)\b)(?!\s*$)")
TS_DEF = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|const|let|class|interface|type|enum)\s+([A-Za-z_]\w*)")
C_KW = {"if", "for", "while", "switch", "return", "sizeof", "else"}
CACHE_VER = 1


def _git(root, *a) -> str:
    try:
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def files(root: pathlib.Path) -> list[str]:
    out = _git(root, "ls-files", "-co", "--exclude-standard").splitlines()
    if not out:
        out = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return sorted(f for f in out if pathlib.PurePosixPath(f).suffix in EXT and not f.startswith(SKIP)
                  and "/" + SKIP[0] not in f)


def defs(path: str, text: str) -> list[tuple[int, str, str]]:
    """(行号, 名字, 那一行) 列表。"""
    out = []
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return out
        lines = text.splitlines()
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append((n.lineno, n.name, lines[n.lineno - 1].strip()))
                if isinstance(n, ast.ClassDef):
                    for m in n.body:
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("__"):
                            out.append((m.lineno, m.name, "    " + lines[m.lineno - 1].strip()))
            elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                    and n.targets[0].id.isupper():
                out.append((n.lineno, n.targets[0].id, lines[n.lineno - 1].strip()[:100]))
        return out
    rx = TS_DEF if path.endswith(".ts") else None
    for i, ln in enumerate(text.splitlines(), 1):
        if rx:
            m = rx.match(ln)
            if m:
                out.append((i, m.group(1), ln.strip()[:120]))
            continue
        m = C_TYPE.match(ln)
        if m:
            out.append((i, next(g for g in m.groups() if g), ln.strip()[:120]))
            continue
        m = C_DEF.match(ln)
        if m and m.group(1) not in C_KW:
            out.append((i, m.group(1), ln.strip().rstrip("{").strip()[:120]))
    return out


def cache_key(root: pathlib.Path) -> str:
    head = _git(root, "rev-parse", "HEAD").strip() or "nogit"
    dirty = _git(root, "status", "--porcelain")
    return f"{head[:12]}-{hashlib.sha1(dirty.encode()).hexdigest()[:8]}"


def tags(root: pathlib.Path, use_cache: bool = True) -> dict:
    """{files: {path: {defs: [...], refs: {ident: n}}}}；同一 git 状态只算一次。"""
    root = pathlib.Path(root)
    key = cache_key(root)
    cdir = snapshots.base_dir() / "codemap"
    cfile = cdir / f"{hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:8]}-{key}.json"
    if use_cache and cfile.exists():
        try:
            d = json.loads(cfile.read_text(encoding="utf-8"))
            if d.get("ver") == CACHE_VER:
                return d
        except ValueError:
            pass
    out = {}
    for f in files(root):
        try:
            text = (root / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out[f] = {"defs": defs(f, text), "refs": dict(Counter(IDENT.findall(text)))}
    d = {"ver": CACHE_VER, "key": key, "files": out}
    if use_cache:
        cdir.mkdir(parents=True, exist_ok=True)
        cfile.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def rank(t: dict, focus: str = "") -> list[tuple[str, float]]:
    """个性化 PageRank：文件 A 引用了 B 定义的名字 → 边 A→B。focus 里提到的文件/标识符加权（aider 的规则）。"""
    fs = t["files"]
    defines = defaultdict(set)
    for f, v in fs.items():
        for _, name, _ in v["defs"]:
            defines[name].add(f)
    words = set(IDENT.findall(focus)) | set(re.findall(r"[\w/.-]+", focus))
    edges = defaultdict(float)
    for ident, definers in defines.items():
        mul = 1.0
        if ident in words:
            mul *= 10
        if ("_" in ident or (any(c.isupper() for c in ident) and any(c.islower() for c in ident))) and len(ident) >= 8:
            mul *= 10
        if ident.startswith("_"):
            mul *= 0.1
        if len(definers) > 5:
            mul *= 0.1
        for f, v in fs.items():
            n = v["refs"].get(ident, 0)
            if not n:
                continue
            for d in definers:
                if d != f:
                    edges[(f, d)] += mul * math.sqrt(n)
    nodes = list(fs)
    if not nodes:
        return []
    pers = {f: (1.0 if any(w and w in f for w in words if "/" in w or "." in w)
                or any(nm in words for _, nm, _ in fs[f]["defs"]) else 0.0) for f in nodes}
    if not any(pers.values()):
        pers = dict.fromkeys(nodes, 1.0)
    s = sum(pers.values())
    pers = {k: v / s for k, v in pers.items()}
    out_w = defaultdict(float)
    for (a, _), w in edges.items():
        out_w[a] += w
    pr = dict(pers)
    for _ in range(40):
        nxt = {f: 0.15 * pers[f] for f in nodes}
        dangling = sum(pr[f] for f in nodes if not out_w[f])
        for f in nodes:
            nxt[f] += 0.85 * dangling * pers[f]
        for (a, b), w in edges.items():
            nxt[b] += 0.85 * pr[a] * w / out_w[a]
        pr = nxt
    return sorted(pr.items(), key=lambda x: -x[1])


def render(root: pathlib.Path, focus: str = "", max_chars: int = 6000, use_cache: bool = True) -> str:
    t = tags(root, use_cache)
    lines, used = [f"# 仓库地图（{t['key']}，按引用排名；focus={focus or '无'}）"], 0
    for f, _ in rank(t, focus):
        ds = t["files"][f]["defs"]
        if not ds:
            continue
        block = [f"{f}:"] + [f"  {ln}: {sig}" for ln, _, sig in ds[:25]] + (["  …"] if len(ds) > 25 else [])
        size = sum(len(x) + 1 for x in block)
        if used + size > max_chars:
            if used == 0:
                block = block[:10]
            else:
                break
        lines += block
        used += size
    return "\n".join(lines)
