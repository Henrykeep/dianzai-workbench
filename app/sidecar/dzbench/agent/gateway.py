"""工具网关：Agent（和“写回 yaml”按钮）对仓库的一切写操作都必须经过这里。

借鉴：
- Claude Code 的权限规则（allow / ask / deny，按工具+路径匹配，deny 优先）
- Aider 的 SEARCH/REPLACE 编辑块 + 每次改动一个 git 提交、可 /undo
- Cursor / OpenHands 的“先出 diff、人审后落地”
在此之上加了嵌入式特有的两条：改完必须过 `make check`（应用层再加 `make test`）才提交；急停不在任何工具表里。
"""
from __future__ import annotations

import difflib
import fnmatch
import itertools
import pathlib
import re
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Callable

from . import yamlpar

ALLOW, ASK, DENY = "allow", "ask", "deny"


def similar_lines(search: str, content: str, threshold: float = 0.6) -> str:
    """SEARCH 没匹配上时找最像的一段给模型看。
    Source: github.com/Aider-AI/aider@5dc9490 aider/coders/editblock_coder.py find_similar_lines（Apache-2.0）
    原样移植；只把变量名缩短。首尾行对得上时只回这段，否则前后各多带 5 行上下文。"""
    s_lines, c_lines = search.splitlines(), content.splitlines()
    best, best_i, best_m = 0.0, 0, None
    for i in range(len(c_lines) - len(s_lines) + 1):
        chunk = c_lines[i:i + len(s_lines)]
        r = difflib.SequenceMatcher(None, s_lines, chunk).ratio()
        if r > best:
            best, best_m, best_i = r, chunk, i
    if best < threshold or not best_m:
        return ""
    if best_m[0] == s_lines[0] and best_m[-1] == s_lines[-1]:
        return "\n".join(best_m)
    lo, hi = max(0, best_i - 5), min(len(c_lines), best_i + len(s_lines) + 5)
    return "\n".join(c_lines[lo:hi])
TRAILER = "Dzbench-Change"

# 自上而下第一条匹配生效；write 的 ASK = 出 diff 等人确认。gates = 确认后、提交前必须通过的命令。
LAYERS: list[dict] = [
    {"layer": "secret", "globs": [".git/*", "*.env", "*secret*", "*.key", "*.pem"], "read": DENY, "write": DENY},
    {"layer": "frozen", "globs": ["firmware/*", "ports/*", "tools/*", "third_party/*", "schema/*", "iface.lock.json",
                                  "Makefile", ".github/*", "app/*", "tests/*", "build/*"],
     "read": ALLOW, "write": DENY, "why": "冻结接口/工具链/工作台自身：只读。要改请人工提交"},
    {"layer": "builtin", "globs": ["examples/*", "boards/*"], "read": ALLOW, "write": DENY,
     "why": "内置例题 / 板卡只读：用户工程在 $DZBENCH_HOME/projects/<名称>/，用户板卡在 $DZ_BOARDS_DIR/<板>/（项目页流程写入）"},
    {"layer": "config", "globs": ["apps/*/app.yaml"],
     "read": ALLOW, "write": ASK, "gates": [["make", "check"]]},
    {"layer": "app", "globs": ["apps/*"], "read": ALLOW, "write": ASK,
     "gates": [["make", "check"], ["make", "test"]]},
    {"layer": "docs", "globs": ["docs/*", "*.md"], "read": ALLOW, "write": ASK, "gates": []},
]
DEFAULT = {"layer": "other", "read": ALLOW, "write": DENY, "why": "不在任何可写层"}
FORBIDDEN_TOOLS = ("estop", "e_stop", "急停")
# 只能由人执行的板上操作：Agent 工具里不提供，调用一律拒绝，只给跳转到界面入口的 fix_action
HUMAN_ONLY = {"set_run_mode": ("切换运行模式（联机/脱机）只能由人在封箱页的确认卡或板上长按完成，Agent 不能执行。",
                               "请到封箱页点击「切换运行模式」，在确认卡上核对后由你本人确认。", "precontest"),
              # 比赛合规底线：启用云端 / 比赛模式开关只能由人在设置页确认卡上改；名字里带这些词的工具一律拒绝
              "cloud_enabled": ("比赛模式下启用云端只能由人在设置页的确认卡上完成，Agent 不能执行。",
                                "请到设置页「云端」点击启用，在确认卡上核对后由你本人确认。", "enable_cloud"),
              "contest_mode": ("比赛模式开关只能由人修改，Agent 不能执行。",
                               "请到设置页「云端」由你本人操作。", "enable_cloud")}


def human_only_error(name: str) -> dict | None:
    """Agent 调用只能由人执行的操作时返回 agent_error 格式（原因 + 怎么解决 + fix_action），否则 None。"""
    for k, (msg, fix, act) in HUMAN_ONLY.items():
        if k in name:
            from ..human_only import mark
            return mark({"type": "agent_error", "code": "human_only", "message": msg, "fix": fix}, act)
    return None


PORCELAIN = re.compile(r"^[ MADRCU?!]{2} \S")
GIT_HINTS = [   # git 原始报错 → 原因 + 处理
    (r"not a git repository", "工程目录不是 git 仓库", "在工程根目录执行 git init 并提交一次，或在设置里把仓库指到正确目录"),
    (r"index\.lock", "另一个 git 进程正在用这个仓库（或上次异常退出留下了锁）", "关掉其他 git 工具；确认没有在跑后删除 .git/index.lock"),
    (r"Please tell me who you are|user\.email", "git 没配置提交人", "git config user.name 你的名字；git config user.email 你的邮箱"),
    (r"pathspec .* did not match", "要提交的文件不在仓库里（路径不对或被删了）", "让 Agent 重新提议"),
    (r"ignored by one of your \.gitignore", "文件被 .gitignore 忽略，无法提交", "换一个不被忽略的路径，或调整 .gitignore"),
    (r"dubious ownership", "git 认为仓库属主不安全", "git config --global --add safe.directory <仓库路径>"),
]


def git_hint(out: str) -> str:
    for pat, cause, fix in GIT_HINTS:
        if re.search(pat, out or ""):
            return f"{cause}。处理：{fix}\n（git 原文：{(out or '').strip()[-300:]}）"
    return f"git 出错（原文：{(out or '').strip()[-300:]}）。处理：检查仓库状态（git status）后让 Agent 重新提议"


class GatewayError(Exception):
    def __init__(self, code: str, message: str, fix: str = "", extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.fix, self.extra = code, message, fix, extra or {}

    def as_dict(self) -> dict:
        return {"type": "error", "code": self.code, "message": self.message, "fix": self.fix} | self.extra


@dataclass
class Change:
    id: int
    title: str
    reason: str
    source: str
    files: dict[str, tuple[str, str]]          # 相对路径 → (旧内容, 新内容)
    layer: str
    gates: list[list[str]]
    status: str = "pending"
    log: str = ""
    commit: str = ""
    diff: str = field(default="")
    git_status: str = ""                        # #88：""（未到提交）/ pending / committed / rejected / failed
    message: str = ""

    def git_card(self) -> dict:
        """#88 提交确认卡：写文件卡只授权写文件；git 提交要人另点这张卡。"""
        return {"type": "git_confirm", "id": self.id, "change_id": self.id, "op": "commit",
                "title_zh": f"提交到 git：{self.title}", "files": list(self.files), "message": self.message,
                "status": self.git_status}

    def card(self) -> dict:
        return {"type": "change", "id": self.id, "title": self.title, "reason": self.reason, "source": self.source,
                "layer": self.layer, "files": list(self.files), "diff": self.diff, "gates": [" ".join(g) for g in self.gates],
                "status": self.status, "log": self.log[-2000:], "commit": self.commit}


def _run(cmd: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       env={**os.environ, "PYTHONUTF8": "1"})
    return r.returncode, (r.stdout + r.stderr)


class Gateway:
    def __init__(self, root: pathlib.Path, emit: Callable[[dict], None] = lambda e: None,
                 runner: Callable[[list[str], pathlib.Path], tuple[int, str]] = _run, layers: list[dict] | None = None):
        self.root = pathlib.Path(root).resolve()
        self.emit, self.runner = emit, runner
        self.layers = layers or LAYERS
        self.changes: dict[int, Change] = {}
        self._ids = itertools.count(1)
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- 权限
    def rel(self, path: str) -> str:
        p = (self.root / path).resolve()
        if self.root not in p.parents and p != self.root:
            raise GatewayError("outside_repo", f"{path} 不在仓库内", "只能访问工作台仓库里的文件")
        return p.relative_to(self.root).as_posix()

    def policy(self, rel: str) -> dict:
        for L in self.layers:
            if any(fnmatch.fnmatch(rel, g) for g in L["globs"]):
                return L
        return DEFAULT

    def check(self, rel: str, op: str) -> dict:
        L = self.policy(rel)
        if L[op] == DENY:
            raise GatewayError("denied", f"{op} {rel}：{L['layer']} 层不允许", L.get("why", ""))
        return L

    # ---------------------------------------------------------------- 只读工具
    def read_file(self, path: str, max_bytes: int = 60_000) -> str:
        rel = self.rel(path)
        self.check(rel, "read")
        p = self.root / rel
        if not p.is_file():
            raise GatewayError("not_found", f"没有文件 {rel}")
        b = p.read_bytes()[:max_bytes]
        return b.decode("utf-8", errors="replace")

    def list_files(self, glob: str = "**/*", limit: int = 300) -> list[str]:
        out = []
        for p in sorted(self.root.glob(glob)):
            if p.is_file():
                rel = p.relative_to(self.root).as_posix()
                if self.policy(rel)["read"] != DENY and not rel.startswith(("build/", "app/ui/node_modules/")):
                    out.append(rel)
                    if len(out) >= limit:
                        break
        return out

    # ---------------------------------------------------------------- 提议改动
    def _propose(self, title: str, reason: str, source: str, files: dict[str, tuple[str, str]]) -> Change:
        layers = [self.check(r, "write") for r in files]
        # 一次改动取最严格的门禁（并集）
        gates: list[list[str]] = []
        for L in layers:
            for g in L.get("gates", []):
                if g not in gates:
                    gates.append(g)
        diff = "".join("".join(difflib.unified_diff(o.splitlines(True), n.splitlines(True), f"a/{r}", f"b/{r}"))
                       for r, (o, n) in files.items())
        if not diff:
            raise GatewayError("no_change", "改动为空（新旧内容相同）")
        with self.lock:
            c = Change(next(self._ids), title, reason, source, files, layers[0]["layer"], gates, diff=diff)
            self.changes[c.id] = c
        self.emit(c.card())
        return c

    def propose_edit(self, path: str, search: str, replace: str, reason: str, source: str = "agent") -> dict:
        """Aider 式 SEARCH/REPLACE：search 必须在文件里恰好出现一次。"""
        rel = self.rel(path)
        self.check(rel, "write")
        p = self.root / rel
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        if search == "" and old:
            raise GatewayError("bad_edit", "search 为空只用于新建文件，但文件已存在")
        n = old.count(search) if search else 1
        if n == 0:
            hint = "先 read_file 看当前内容，search 要逐字复制（含缩进、空行）"
            if replace and replace in old:
                hint = f"replace 的内容已经在 {rel} 里了——这处改动可能已经做过，不用再改"
            elif near := similar_lines(search, old):
                hint = f"你是不是想匹配 {rel} 里这几行？请照它逐字重写 search：\n{near}"
            raise GatewayError("bad_edit", f"search 文本在 {rel} 中没有找到", hint)
        if n != 1:
            raise GatewayError("bad_edit", f"search 文本在 {rel} 中出现 {n} 次（需要恰好 1 次）", "多带几行上下文让它唯一")
        new = old.replace(search, replace, 1) if search else replace
        return self._propose(f"编辑 {rel}", reason, source, {rel: (old, new)}).card()

    def propose_yaml_params(self, path: str, values: dict[str, float], reason: str, source: str = "user") -> dict:
        rel = self.rel(path)
        old = (self.root / rel).read_text(encoding="utf-8")
        new, missing = yamlpar.rewrite(old, values)
        if missing:
            raise GatewayError("bad_param", f"{rel} 里找不到参数：{', '.join(missing)}")
        changed = sum(a != b for a, b in zip(old.splitlines(), new.splitlines()))
        if not changed:
            raise GatewayError("no_change", f"{rel} 里的默认值已经和板上一致，不用写回")
        title = f"写回参数默认值 → {rel}（改 {changed} 项，共核对 {len(values)} 项）"
        return self._propose(title, reason, source, {rel: (old, new)}).card()

    # ---------------------------------------------------------------- 决定
    def _git(self, *args: str) -> tuple[int, str]:
        return self.runner(["git", *args], self.root)

    def decide(self, cid: int, accept: bool) -> dict:
        with self.lock:
            c = self.changes.get(cid)
            if not c or c.status != "pending":
                raise GatewayError("no_change", f"改动 {cid} 不存在或已处理")
            c.status = "applying" if accept else "rejected"
        if not accept:
            self.emit(c.card())
            return c.card()
        try:
            self._apply(c)
        finally:
            self.emit(c.card())
        return c.card()

    def _apply(self, c: Change) -> None:
        # 1. 工作区里这些文件必须干净，且内容仍是提议时的旧内容（防止覆盖人手改动）
        rc, out = self._git("status", "--porcelain", "--", *c.files)
        if rc != 0:
            c.status, c.log = "failed", git_hint(out)
            return
        dirty = [ln for ln in out.splitlines() if PORCELAIN.match(ln)              # 只看状态行；warning（新目录不存在等）不算
                 and not (ln.startswith("?? ") and not c.files.get(ln[3:].strip().strip('"'), ("x",))[0])]   # 新建文件（旧内容为空）未跟踪不算
        if dirty:
            c.status, c.log = "failed", "这些文件有未提交的改动（防止覆盖你的手改）：\n" + "\n".join(dirty) + "\n处理：先提交或撤销这些改动，再让 Agent 重新提议"
            return
        for r, (old, _) in c.files.items():
            p = self.root / r
            if (p.read_text(encoding="utf-8") if p.exists() else "") != old:
                c.status, c.log = "failed", f"{r} 在提议之后被改过，请重新生成提议"
                return
        # 2. 写入 → 门禁 → 失败则原样恢复
        for r, (_, new) in c.files.items():
            (self.root / r).parent.mkdir(parents=True, exist_ok=True)
            (self.root / r).write_text(new, encoding="utf-8")
        logs = []
        for g in c.gates:
            rc, out = self.runner(g, self.root)
            logs.append(f"$ {' '.join(g)}  → {rc}\n{out[-3000:]}")
            if rc != 0:
                for r, (old, _) in c.files.items():
                    if old:
                        (self.root / r).write_text(old, encoding="utf-8")
                    else:
                        (self.root / r).unlink(missing_ok=True)
                c.status, c.log = "failed", "门禁未通过，已恢复原文件：\n" + "\n".join(logs)
                return
        # 3. #88：文件已写入、门禁通过；提交另出确认卡，人点了才提交
        c.status, c.log = "written", "\n".join(logs) or "（该层无门禁）"
        c.message = f"{c.title}\n\n{c.reason}\n\n{TRAILER}: {c.id} ({c.source})"
        c.git_status = "pending"
        self.emit(c.git_card())

    GIT_MUTATIONS = ("commit", "branch", "reset", "push", "tag", "merge", "rebase", "checkout", "revert", "stash", "cherry-pick")

    def git_mutate(self, op: str, *args: str, approved: bool = False) -> dict:
        """#88：Agent 发起的任何 git 写操作，没经确认卡批准一律拒绝。"""
        if op in self.GIT_MUTATIONS and not approved:
            return {"ok": False, "op": op, "reason_zh": f"git {op} 会改动仓库历史或分支，需要你在确认卡上批准，未执行",
                    "fix_action": "propose_git_confirm"}
        rc, out = self._git(op, *args)
        return {"ok": rc == 0, "op": op, "output": out[-2000:]}

    def commit_decide(self, cid: int, accept: bool) -> dict:
        with self.lock:
            c = self.changes.get(cid)
            if not c or c.git_status != "pending":
                raise GatewayError("no_change", f"提交 {cid} 不存在或已处理")
            c.git_status = "committing" if accept else "rejected"
        if not accept:
            self.emit(c.git_card())
            return {"ok": False, **c.git_card(), "reason_zh": "你没有批准提交：文件已写入工作区，但没有做 git 提交",
                    "fix_action": "commit_manually_or_reopen"}
        try:
            self._commit(c)
        finally:
            c.git_status = "committed" if c.status == "committed" else "failed"
            self.emit(c.git_card())
            self.emit(c.card())
        if c.status != "committed":
            return {"ok": False, **c.git_card(), "reason_zh": c.log[-500:], "fix_action": "retry_commit"}
        return {"ok": True, **c.card()}

    def _commit(self, c: Change) -> None:
        logs, msg = c.log, c.message
        self._git("add", "--", *c.files)
        rc, out = self.runner(["git", "-c", "user.name=dzbench", "-c", "user.email=dzbench@localhost", "commit", "-q", "-m", msg,
                               "--", *c.files] if not self._has_identity() else ["git", "commit", "-q", "-m", msg, "--", *c.files], self.root)
        if rc != 0:
            c.status, c.log = "written", logs + "\ngit commit 失败：" + git_hint(out)
            return
        _, sha = self._git("rev-parse", "--short", "HEAD")
        c.status, c.commit = "committed", sha.strip()

    def _has_identity(self) -> bool:
        return self._git("config", "user.email")[0] == 0

    def rollback(self, commit: str) -> dict:
        rc, body = self._git("log", "-1", "--format=%B", commit)
        if rc != 0 or f"{TRAILER}:" not in body:
            raise GatewayError("not_agent_commit", f"{commit} 不是工作台产生的提交，拒绝回滚", "人工提交请用 git 自己处理")
        _, files = self._git("show", "--name-only", "--format=", commit)
        files = [f for f in files.splitlines() if f.strip()]
        if files:   # Aider cmd_undo：那次提交改过的文件现在有未提交改动就拒绝，免得 revert 把用户手改的混进去或冲突
            _, dirty = self._git("status", "--porcelain", "--", *files)
            if dirty.strip():
                raise GatewayError("dirty", f"{', '.join(files[:3])} 有未提交的改动，先保存/提交或丢弃再撤销",
                                   "git stash 或提交后再点撤销")
        args = ["revert", "--no-edit", commit]
        rc, out = self.runner((["git", "-c", "user.name=dzbench", "-c", "user.email=dzbench@localhost"] if not self._has_identity() else ["git"]) + args, self.root)
        if rc != 0:
            self._git("revert", "--abort")
            raise GatewayError("revert_failed", f"回滚 {commit} 冲突：{out[-500:]}", "后面的提交改了同一处，手动处理")
        _, sha = self._git("rev-parse", "--short", "HEAD")
        return {"reverted": commit, "commit": sha.strip()}

    def history(self, n: int = 20) -> list[dict]:
        rc, out = self._git("log", f"-{n * 5}", f"--grep={TRAILER}:", "--format=%h%x09%cI%x09%s")
        rows = [dict(zip(("commit", "time", "title"), l.split("\t", 2))) for l in out.splitlines() if l.count("\t") >= 2] if rc == 0 else []
        return rows[:n]

    def pending(self) -> list[dict]:
        return [c.card() for c in self.changes.values() if c.status == "pending"] + \
               [c.git_card() for c in self.changes.values() if c.git_status == "pending"]
