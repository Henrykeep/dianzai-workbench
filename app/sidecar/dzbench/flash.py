"""烧录（pyOCD 优先），带前置条件、默认 dry-run、烧前备份、烧后心跳校验、一键回滚。风险等级 human（必须人点）。

思路参考 embeddedskills（MIT）的 flash 技能：烧前检查 + 烧后验证。前置条件为本项目自定：
1. 最近一次编译成功，且镜像文件自那以后没被改过（sha256）
2. 探针读到的 DP IDCODE 与目标内核一致（防止插错板）
3. 急停已锁存（侧车 tx_locked）——烧录会复位芯片，电机必须先停
4. 默认 dry_run=True：只返回将要做的步骤，不动板子；人确认后带 dry_run=False 再调一次
烧后：等心跳，schema 哈希必须等于本次编译生成的 link_schema.json；否则提示一键回滚到烧前备份。
⚠ 测试：MockBackend 单测 + tests/fakepyocd（假 pyOCD 包，走真实 PyOCDBackend 代码）端到端；真实 pyOCD + 探针 未实测。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time

from . import snapshots
from .hardfault import guess_core

# ADIv5 DPIDR（SW-DP）：架构文档公开值；不同厂商可能不同，必要时在 dzbench.json 里写 flash.idcode 覆盖
DPIDR = {"cm0": 0x0BB11477, "cm0plus": 0x0BC11477, "cm3": 0x1BA01477, "cm4": 0x2BA01477, "cm7": 0x5BA02477}
FLASH_BASE = {"mspm0": 0x00000000, "stm32": 0x08000000}


class FlashError(Exception):
    def __init__(self, code: str, message: str, fix: str = ""):
        super().__init__(message)
        self.code, self.message, self.fix = code, message, fix


def sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# pyOCD 不内置 MSPM0，要 TI 的 CMSIS 器件包（DFP，BSD-3-Clause）。安装包自带一份（tools/fetch_third_party.sh m0pack），
# 找不到再用 pyOCD 自己管理的包（pyocd pack install mspm0g3507，需要联网）。
M0_PACK = "TexasInstruments.MSPM0G1X0X_G3X0X_DFP.1.3.1.pack"


def find_pack(target: str) -> pathlib.Path | None:
    import os
    import sys
    if not (target or "").lower().startswith("mspm0"):
        return None
    here = pathlib.Path(__file__).resolve()
    cands = [os.environ.get("DZBENCH_PACK", ""),
             pathlib.Path(getattr(sys, "_MEIPASS", "")) / "packs" / M0_PACK if getattr(sys, "_MEIPASS", None) else "",
             here.parents[3] / "third_party" / "packs" / M0_PACK,
             snapshots.base_dir() / "packs" / M0_PACK]
    return next((pathlib.Path(c) for c in cands if c and pathlib.Path(c).is_file()), None)


class PyOCDBackend:
    """真实探针（需要 `pip install pyocd`）。⚠ 未实测。"""
    def __init__(self, target: str, probe: str | None = None):
        try:
            from pyocd.core.helpers import ConnectHelper  # type: ignore
        except ImportError as e:
            raise FlashError("no_pyocd", "没装 pyOCD", "pip install pyocd") from e
        pack = find_pack(target)
        if (target or "").lower().startswith("mspm0") and not pack:
            raise FlashError("no_pack", f"找不到 MSPM0 器件包 {M0_PACK}",
                             "运行 tools/fetch_third_party.sh m0pack，或联网执行 pyocd pack install mspm0g3507，或设 DZBENCH_PACK=包路径")
        kw = {"pack": str(pack)} if pack else {}
        self.sess = ConnectHelper.session_with_chosen_probe(unique_id=probe, target_override=target, blocking=False, **kw)
        if self.sess is None:
            raise FlashError("no_probe", "没找到调试探针", "插上 DAPLink/ST-Link/XDS110，确认驱动")
        self.sess.open()

    def idcode(self) -> int:
        return int(self.sess.target.dp.dpidr.idr)

    def read(self, addr: int, n: int) -> bytes:
        return bytes(self.sess.target.read_memory_block8(addr, n))

    def load(self, path: str, base: int) -> None:
        from pyocd.flash.file_programmer import FileProgrammer  # type: ignore
        FileProgrammer(self.sess).program(path, base_address=base if path.endswith(".bin") else None)

    def flash_size(self) -> int | None:
        try:
            return int(self.sess.target.memory_map.get_boot_memory().length)
        except Exception:  # noqa: BLE001  拿不到就按镜像/默认大小备份
            return None

    def reset(self) -> None:
        self.sess.target.reset()

    def close(self) -> None:
        self.sess.close()


class MockBackend:
    def __init__(self, idcode: int = DPIDR["cm0plus"], flash: bytes = b"\xff" * 64):
        self._id, self.flash, self.loaded, self.resets = idcode, bytearray(flash), [], 0

    def idcode(self) -> int:
        return self._id

    def read(self, addr: int, n: int) -> bytes:
        return bytes(self.flash[:n])

    def load(self, path: str, base: int) -> None:
        self.loaded.append(path)
        d = pathlib.Path(path).read_bytes()
        self.flash[: len(d)] = d

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        pass


class Flasher:
    def __init__(self, session, cfg: dict, backend_factory=None):
        self.s, self.cfg = session, cfg
        self.factory = backend_factory or (lambda: PyOCDBackend(cfg["flash"]["target"], cfg["flash"].get("probe")))
        self.last_build: dict | None = None
        self.backups: list[pathlib.Path] = []
        self.prev_schema_hash: int | None = None        # 烧之前板上跑的固件（回滚后按它校验）

    def note_build(self, ok: bool, image: str, schema_hash: int | None = None) -> None:
        p = pathlib.Path(image)
        self.last_build = {"ok": ok, "image": str(p), "sha256": sha256(p) if ok and p.exists() else None,
                           "schema_hash": schema_hash, "t": time.time()}

    def preconditions(self) -> list[dict]:
        f, out = self.cfg["flash"], []
        b = self.last_build
        img_ok = bool(b and b["ok"] and pathlib.Path(b["image"]).exists() and sha256(pathlib.Path(b["image"])) == b["sha256"])
        out.append({"name": "build_ok", "ok": img_ok, "why": "最近一次编译成功且镜像未变" if img_ok else "先编译成功一次（镜像在编译后被改过也要重编）"})
        out.append({"name": "estop_latched", "ok": bool(self.s.tx_locked),
                    "why": "急停已锁存" if self.s.tx_locked else "先按急停：烧录会复位芯片，电机必须先停"})
        out.append({"name": "target", "ok": bool(f.get("target")), "why": f"目标 {f.get('target')}" if f.get("target") else "dzbench.json 里写 flash.target（如 mspm0g3507 / stm32f103c8）"})
        return out

    def _expect_idcode(self) -> int | None:
        if self.cfg["flash"].get("idcode"):
            return int(str(self.cfg["flash"]["idcode"]), 0)
        core = self.cfg.get("core") or guess_core(self.cfg["flash"].get("target"))
        return DPIDR.get(core or "")

    def flash(self, dry_run: bool | None = None) -> dict:
        dry = self.cfg["flash"]["dry_run"] if dry_run is None else dry_run
        pre = self.preconditions()
        tgt = (self.cfg["flash"].get("target") or "").lower()
        base = next((v for k, v in FLASH_BASE.items() if tgt.startswith(k)), 0x08000000)
        plan = {"dry_run": dry, "preconditions": pre, "image": (self.last_build or {}).get("image"), "base": f"0x{base:08x}",
                "steps": ["连接探针并核对 IDCODE", "备份当前固件（同镜像大小）", "烧录镜像", "复位", "等心跳并核对 schema 哈希"]}
        bad = [p for p in pre if not p["ok"]]
        if bad:
            raise FlashError("precondition", "烧录前置条件不满足：" + "；".join(p["why"] for p in bad))
        if dry:
            return plan | {"status": "dry_run", "hint": "确认无误后在界面点“确认烧录”（dry_run=false）"}
        be = self.factory()
        try:
            exp, got = self._expect_idcode(), be.idcode()
            if exp is not None and got != exp:
                raise FlashError("idcode", f"芯片 IDCODE 0x{got:08x} ≠ 期望 0x{exp:08x}（{tgt}）", "是不是插错板 / 选错目标？")
            img = pathlib.Path(self.last_build["image"])
            if self.cfg["flash"].get("keep_previous", True):
                bk = snapshots.base_dir() / "flash_backup" / f"{time.strftime('%Y%m%d_%H%M%S')}_{tgt or 'chip'}.bin"
                bk.parent.mkdir(parents=True, exist_ok=True)
                # .bin 按镜像大小备份；ELF/HEX 备份整片（读不到片上 Flash 大小时最多 256 KB）
                size = img.stat().st_size if img.suffix == ".bin" else min(256 * 1024, getattr(be, "flash_size", lambda: None)() or 256 * 1024)
                bk.write_bytes(be.read(base, size))
                self.backups.append(bk)
            self.prev_schema_hash = self.s.schema_hash
            be.load(str(img), base)
            t_reset = time.monotonic()
            be.reset()
        finally:
            be.close()
        return plan | {"status": "flashed", "verify": self.verify(after=t_reset), "backup": str(self.backups[-1]) if self.backups else None}

    def verify(self, timeout: float | None = None, after: float | None = None, expect: int | None | bool = False) -> dict:
        """等一帧复位之后的新心跳（after = 复位时刻；只看旧心跳会把“板子没起来”误判成成功）。"""
        exp = (self.last_build or {}).get("schema_hash") if expect is False else expect
        timeout = self.cfg["flash"]["heartbeat_timeout_s"] if timeout is None else timeout
        if not self.s.tr:
            return {"ok": None, "why": "串口没连：无法用心跳校验，连上后点“校验”"}
        t_end = time.monotonic() + timeout
        while time.monotonic() < t_end:
            fresh = after is None or self.s.last_hb > after
            if fresh and self.s.schema_hash is not None and (exp is None or self.s.schema_hash == exp):
                return {"ok": True, "schema_hash": f"{self.s.schema_hash:08X}"}
            time.sleep(0.05)
        return {"ok": False, "why": "烧后没收到匹配的心跳", "fix": "看串口/供电；不行就点“回滚到烧前固件”",
                "got": None if self.s.schema_hash is None else f"{self.s.schema_hash:08X}",
                "expected": None if exp is None else f"{exp:08X}"}

    def rollback(self, dry_run: bool | None = None) -> dict:
        if not self.backups:
            raise FlashError("no_backup", "没有烧前备份")
        if not self.s.tx_locked:
            raise FlashError("precondition", "先按急停再回滚")
        dry = self.cfg["flash"]["dry_run"] if dry_run is None else dry_run
        bk = self.backups[-1]
        if dry:
            return {"status": "dry_run", "image": str(bk)}
        tgt = (self.cfg["flash"].get("target") or "").lower()
        base = next((v for k, v in FLASH_BASE.items() if tgt.startswith(k)), 0x08000000)
        be = self.factory()
        try:
            be.load(str(bk), base)
            t_reset = time.monotonic()
            be.reset()
        finally:
            be.close()
        return {"status": "rolled_back", "image": str(bk), "verify": self.verify(after=t_reset, expect=self.prev_schema_hash)}


def schema_hash_of(link_schema: str | pathlib.Path) -> int | None:
    p = pathlib.Path(link_schema)
    if not p.exists():
        return None
    h = json.loads(p.read_text(encoding="utf-8")).get("hash")
    return int(h, 16) if isinstance(h, str) else h
