"""协处理器 SSH 部署（缺口 12）：MaixCAM / K230 / Jetson / 树莓派 / RDK。

推脚本（scp -r）、后台启动（nohup，pid 写 dz.pid，输出写 dz.log）、停止、看状态、看日志尾巴。
只用系统的 ssh / scp，强制 BatchMode=yes：只走密钥登录，不存密码（密码 / 口令绝不进配置文件）。
配置存本机 ~/.dzbench/machine.json 的 "coproc" 键；测试用 DZBENCH_SSH / DZBENCH_SCP 换成假程序。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess

from . import snapshots
from .session import LinkError

# 各板默认：登录用户、远端目录、启动命令（{entry} = 入口脚本名）。都可在对话框里改。
PRESETS = {
    "maixcam": {"label": "MaixCAM（Sipeed）", "user": "root", "dir": "/root/dz", "run": "python3 {entry}"},
    "k230":    {"label": "K230（CanMV Linux）", "user": "root", "dir": "/sharefs/dz", "run": "python3 {entry}"},
    "jetson":  {"label": "Jetson", "user": "jetson", "dir": "~/dz", "run": "python3 {entry}"},
    "rpi":     {"label": "树莓派", "user": "pi", "dir": "~/dz", "run": "python3 {entry}"},
    "rdk":     {"label": "地平线 RDK", "user": "sunrise", "dir": "~/dz", "run": "python3 {entry}"},
}
KEYS = ("kind", "host", "port", "user", "dir", "entry", "run", "key")
_HOST = re.compile(r"^[A-Za-z0-9_.:\-]+$")
_USER = re.compile(r"^[A-Za-z0-9_.\-]+$")


class DeployError(LinkError):
    pass


def _machine() -> pathlib.Path:
    return snapshots.base_dir() / "machine.json"


def load() -> dict:
    try:
        m = json.loads(_machine().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    c = dict(m.get("coproc") or {})
    kind = c.get("kind") or "maixcam"
    p = PRESETS.get(kind, PRESETS["maixcam"])
    out = {"kind": kind, "host": "", "port": 22, "user": p["user"], "dir": p["dir"], "entry": "main.py", "run": p["run"], "key": ""}
    out.update({k: v for k, v in c.items() if k in KEYS and v not in (None, "")})
    out["port"] = int(out["port"])
    return out


def validate(c: dict) -> dict:
    if c.get("kind") not in PRESETS:
        raise DeployError("bad_kind", f"不认识的协处理器 {c.get('kind')}")
    if c.get("host") and not _HOST.match(c["host"]):
        raise DeployError("bad_host", "主机名只能是 IP / 域名")
    if not _USER.match(str(c.get("user", ""))):
        raise DeployError("bad_user", "用户名只能是字母数字 _ . -")
    if not (0 < int(c.get("port", 22)) < 65536):
        raise DeployError("bad_port", "端口 1~65535")
    if "/" in str(c.get("entry", "")) or not c.get("entry"):
        raise DeployError("bad_entry", "入口脚本写文件名（在远端目录里），如 main.py")
    for k in ("password", "passwd", "pass"):
        if k in c:
            raise DeployError("no_password", "不存密码：请给协处理器配 SSH 密钥（ssh-copy-id）")
    return c


def save(values: dict) -> dict:
    cur = load()
    if values.get("kind") and values["kind"] != cur["kind"]:      # 换板子：没手填的项回到该板默认
        p = PRESETS.get(values["kind"], {})
        cur.update({"user": p.get("user", cur["user"]), "dir": p.get("dir", cur["dir"]), "run": p.get("run", cur["run"])})
    cur.update({k: values[k] for k in KEYS if k in values and values[k] not in (None, "")})
    if any(k in values for k in ("password", "passwd", "pass")):
        validate(values)
    validate(cur)
    p = _machine()
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    m["coproc"] = {k: cur[k] for k in KEYS}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return load()


def _rdir(d: str) -> str:
    """远端目录：~ 开头交给远端 shell 展开，其余加引号。"""
    if d.startswith("~/"):
        return '"$HOME"/' + shlex.quote(d[2:])
    return shlex.quote(d)


class Deployer:
    def __init__(self, cfg: dict | None = None, timeout: float = 20.0):
        self.c = validate(dict(cfg or load()))
        self.timeout = timeout

    def _base(self, exe_env: str, exe: str) -> list[str]:
        e = os.environ.get(exe_env) or shutil.which(exe)
        if not e:
            raise DeployError("no_ssh", f"找不到 {exe}：装 OpenSSH 客户端（Windows 10+ 自带，设置 → 可选功能）")
        a = [e, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]
        if self.c.get("key"):
            a += ["-i", os.path.expanduser(self.c["key"])]
        return a

    def _dest(self) -> str:
        if not self.c.get("host"):
            raise DeployError("no_host", "先在对话框里填协处理器 IP")
        return f"{self.c['user']}@{self.c['host']}"

    def ssh(self, cmd: str) -> subprocess.CompletedProcess:
        a = self._base("DZBENCH_SSH", "ssh") + ["-p", str(self.c["port"]), self._dest(), cmd]
        try:
            r = subprocess.run(a, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise DeployError("timeout", f"ssh 超时（{self.timeout:.0f} s）：板子开机了吗、IP 对吗") from None
        if r.returncode == 255:
            raise DeployError("ssh_fail", (r.stderr.strip() or "ssh 连不上") + "（只走密钥登录：先 ssh-copy-id）")
        return r

    def push(self, local: str) -> dict:
        src = pathlib.Path(local).expanduser()
        if not src.exists():
            raise DeployError("no_src", f"本地没有 {src}")
        d = _rdir(self.c["dir"])
        self.ssh(f"mkdir -p {d}")
        files = [src] if src.is_file() else sorted(x for x in src.iterdir() if not x.name.startswith("."))
        a = self._base("DZBENCH_SCP", "scp") + ["-r", "-P", str(self.c["port"])] + [str(f) for f in files]
        rd = self.c["dir"]
        a.append(f"{self._dest()}:{rd}/")
        try:
            r = subprocess.run(a, capture_output=True, text=True, timeout=max(self.timeout, 120))
        except subprocess.TimeoutExpired:
            raise DeployError("timeout", "scp 超时") from None
        if r.returncode:
            raise DeployError("scp_fail", r.stderr.strip() or f"scp 退出码 {r.returncode}")
        return {"pushed": [f.name for f in files], "to": f"{self._dest()}:{rd}"}

    def start(self) -> dict:
        if self.status()["running"]:
            raise DeployError("running", "已经在跑了，先停")
        d = _rdir(self.c["dir"])
        run = self.c["run"].replace("{entry}", shlex.quote(self.c["entry"]))
        cmd = f"cd {d} && (nohup sh -c {shlex.quote(run)} > dz.log 2>&1 < /dev/null & echo $! > dz.pid) && cat dz.pid"
        r = self.ssh(cmd)
        if r.returncode:
            raise DeployError("start_fail", r.stderr.strip() or "启动失败")
        return {"pid": int(r.stdout.strip().splitlines()[-1]), "run": run}

    def stop(self) -> dict:
        d = _rdir(self.c["dir"])
        r = self.ssh(f"cd {d} && [ -f dz.pid ] && p=$(cat dz.pid) && (kill $p 2>/dev/null; sleep 1; kill -9 $p 2>/dev/null; rm -f dz.pid; echo stopped $p) || echo none")
        out = r.stdout.strip()
        return {"stopped": out.startswith("stopped"), "detail": out}

    def status(self) -> dict:
        d = _rdir(self.c["dir"])
        r = self.ssh(f"cd {d} 2>/dev/null && [ -f dz.pid ] && kill -0 $(cat dz.pid) 2>/dev/null && echo run $(cat dz.pid) || echo idle")
        w = r.stdout.split()
        return {"running": bool(w) and w[0] == "run", "pid": int(w[1]) if len(w) > 1 and w[0] == "run" else None}

    def log(self, lines: int = 100) -> dict:
        n = max(1, min(int(lines), 2000))
        d = _rdir(self.c["dir"])
        r = self.ssh(f"tail -n {n} {d}/dz.log 2>/dev/null || true")
        return {"text": r.stdout}
