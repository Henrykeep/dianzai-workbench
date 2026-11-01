"""link_schema.json：按心跳里的哈希自动匹配（零配置），并按字段表解码遥测。"""
from __future__ import annotations

import json
import os
import pathlib
import struct

from .transport import ROOT

FMT = {"f32": "f", "u32": "I", "i32": "i", "u16": "H", "i16": "h", "u8": "B"}


class Schema:
    def __init__(self, d: dict, path: str = ""):
        self.d, self.path = d, path
        # 板端上位机看门狗阈值（嵌入式开发-2 在握手里上报；没报 = None，不编造）
        wd = d.get("wd_timeout_ms", (d.get("link") or {}).get("wd_timeout_ms") if isinstance(d.get("link"), dict) else None)
        self.wd_timeout_ms = int(wd) if isinstance(wd, (int, float)) and wd > 0 else None
        self.hash = int(d["hash"])
        tel = d["telemetry"]
        self.telem_id = tel["id"]
        self.fields = tel["fields"]
        self._fmt = "<" + "".join(FMT[f["type"]] for f in self.fields)
        self.size = struct.calcsize(self._fmt)
        self.params = d.get("params", [])
        self.param_index = {p["name"]: i for i, p in enumerate(self.params)}

    @classmethod
    def load(cls, path) -> "Schema":
        return cls(json.loads(pathlib.Path(path).read_text(encoding="utf-8")), str(path))

    def decode(self, payload: bytes) -> dict | None:
        if len(payload) != self.size:
            return None
        return dict(zip((f["name"] for f in self.fields), struct.unpack(self._fmt, payload)))

    def check(self, name: str, raw, current: float | None = None) -> float:
        """#40/#38：写参数前按 link_schema.json（app.yaml link.params）校验类型、[min, max]，给了当前值时再查
        单步 |新 − 旧| ≤ max_delta（固件同样会回 param_reject reason=step）。不合法直接拒绝（invalid_param），从不钳位。"""
        p = self.params[self.param_index[name]] if name in self.param_index else None
        v = check_value(name, raw, p)
        md = max_delta(p) if p else None
        if md is not None and current is not None and abs(v - float(current)) > md + 1e-9 * max(1.0, md):
            raise _invalid(name, f"单步改动 {abs(v - float(current)):g} 超过 max_delta {md:g}（当前 {float(current):g}）", p, "step")
        return v

    @property
    def step(self) -> list[dict]:
        """app.yaml link.step（#38 阶跃通道：sp / y / u / u_max / range / abs_tol），老 schema 为空。"""
        return list(self.d.get("step") or [])

    def setpoints(self) -> list[dict]:
        """设定值通道（DATA id=1 第 i 个 f32 = 遥测里第 i 个带 ref_for 的字段）。hold = latched | timeout 原样透传
        （app.yaml link 设定值通道的 hold：先看 link.step 里 sp 同槽的条目，再看遥测字段本身）；缺省 = timeout。"""
        out = []
        for i, f in enumerate(x for x in self.fields if x.get("ref_for")):
            st = next((c for c in self.step if int(c.get("sp", -1)) == i), {})
            out.append({"name": f["name"], "slot": i, "ref_for": f["ref_for"], "hold": st.get("hold") or f.get("hold") or "timeout"})
        return out

    def summary(self) -> dict:
        return {"hash": f"{self.hash:08X}", "path": self.path, "fields": self.fields, "params": self.params,
                "period_ms": self.d["telemetry"].get("period_ms"),
                # 只给界面：验收规格、串级分层（gen_link 从 yaml link: 段原样带过来；字段的 cal 在 fields 里）
                "accept": self.d.get("accept") or [], "loops": self.d.get("loops") or [],
                "protect_fixed": self.d.get("protect_fixed") or [],
                "step": self.step, "setpoints": self.setpoints()}


def search_dirs() -> list[pathlib.Path]:
    extra = os.environ.get("DZBENCH_SCHEMA_DIRS", "")
    # 环境变量 → 仓库 build/（开发/源码运行）→ ~/.dzbench/schemas（打包版：把 link_schema.json 拷进去）
    from .snapshots import base_dir
    return [pathlib.Path(p) for p in extra.split(os.pathsep) if p] + ([pathlib.Path(os.environ["DZBENCH_REPO"]) / "build"] if os.environ.get("DZBENCH_REPO") else []) + [ROOT / "build", base_dir() / "schemas"]


CONFLICT_FIX = "clear_schema_cache"
REBUILD_FIX = "build"                # 冲突只涉及编译产物（或编译产物对板子 'I' 回包）：重新编译并烧录，不是清缓存


def cache_dir() -> pathlib.Path:
    """侧车自己的格式缓存目录（~/.dzbench/schemas）。clear_schema_cache 只删这里面的文件。"""
    from .snapshots import base_dir
    return base_dir() / "schemas"


def file_kind(p) -> str:
    """cache = 侧车缓存拷贝（可删）；build = 编译产物 / 工程 / 仓库里的文件（永不删）。"""
    try:
        pathlib.Path(p).resolve().relative_to(cache_dir().resolve())
        return "cache"
    except (ValueError, OSError):
        return "build"   # 入口规则表 docs/dev/entrypoints.yaml 的动作 id：界面确认卡 → op clear_schema_cache {hash}


class SchemaConflict(Exception):
    """同一个哈希在本机匹配到多份内容不同的 link_schema.json（例如两块板子来回插、哈希没把板子身份 / wd_timeout_ms 算进去）。
    不挑第一份、也不挑最新的一份：挑错了界面就会按错的通道和参数去显示、去写。"""

    def __init__(self, h: int, paths: list[str], board_uid: str | None = None, message_zh: str | None = None):
        self.hash, self.paths, self.board_uid = h, paths, board_uid
        names = "；".join(paths)
        self.message_zh = message_zh or (f"板子的数据格式（哈希 {h:08X}）在本机对应到 {len(paths)} 份内容不同的格式文件，无法判断是哪一块板子的。"
                           "为避免按错的通道和参数显示或写入，已停止显示遥测和写参数。")
        self.kinds = [file_kind(p) for p in paths]
        if "cache" in self.kinds:
            self.fix_zh = "清掉本机缓存的这个哈希的格式文件后重新识别板子；仍不对就按当前这块板子重新编译并烧录固件。"
            self.fix_action = CONFLICT_FIX
        else:                          # 只有编译产物（或编译产物对板子 'I' 回包）：清缓存没用，也绝不删编译产物
            self.fix_zh = "编译产物和板子上的固件对不上：按当前这块板子重新编译并烧录固件。"
            self.fix_action = REBUILD_FIX
        super().__init__(f"{self.message_zh}（{names}）")

    def as_dict(self) -> dict:
        return {"type": "error", "code": "schema_conflict", "reason": "schema_conflict", "message": self.message_zh,
                "message_zh": self.message_zh, "fix": self.fix_zh, "fix_action": self.fix_action,
                "hash": f"{self.hash:08X}", "board_uid": self.board_uid,
                "files": [{"path": str(pathlib.Path(p).resolve()), "kind": k} for p, k in zip(self.paths, self.kinds)]}


def _canon(d: dict) -> str:
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def find_by_hash(h: int) -> Schema | None:
    """在所有搜索目录里找哈希为 h 的 link_schema.json。
    内容完全相同的多份（比如 build/ 与 ~/.dzbench/schemas 里的拷贝）算同一份，取搜索顺序里的第一份；
    内容不同的多份 → SchemaConflict（不取第一份、不取最新的一份）。找不到 → None。"""
    hits: dict[str, Schema] = {}
    for d in search_dirs():
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("link_schema.json")):
            try:
                s = Schema.load(f)
            except (ValueError, KeyError, OSError):
                continue
            if s.hash == h:
                hits.setdefault(_canon(s.d), s)
    if len(hits) > 1:
        raise SchemaConflict(h, [s.path for s in hits.values()])
    return next(iter(hits.values()), None)


def schema_files(h: int) -> list[pathlib.Path]:
    """所有搜索目录里哈希为 h 的 link_schema.json（绝对路径）。"""
    out = []
    for d in search_dirs():
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("link_schema.json")):
            try:
                if Schema.load(f).hash == h:
                    out.append(f.resolve())
            except (ValueError, KeyError, OSError):
                continue
    return list(dict.fromkeys(out))


def clear_cache(h: int) -> list[str]:
    """op clear_schema_cache：只删侧车缓存（cache_dir）里哈希为 h 的格式文件，别的哈希、编译产物一个不碰。返回删掉的绝对路径。"""
    removed = []
    for f in schema_files(h):
        if file_kind(f) != "cache":         # 编译产物 / 工程 / 仓库里的文件一律不删
            continue
        try:
            f.unlink()
            removed.append(str(f))
        except OSError:
            continue
    return removed


def max_delta(p: dict) -> float | None:
    """link_schema.json 的 max_delta；老 schema 没有 = max − min（不限制）。"""
    if p.get("max_delta") is not None:
        return float(p["max_delta"])
    return float(p["max"]) - float(p["min"]) if "min" in p and "max" in p else None


def _invalid(name: str, why: str, p: dict | None, code: str | None = None):
    from .session import LinkError
    rng = f"{p['min']:g} ~ {p['max']:g}" if p and "min" in p and "max" in p else ""
    integral = bool(p) and p.get("type", "f32") != "f32"
    eg = (f"{int(p['min'])}" if integral else f"{(p['min'] + p['max']) / 2:g}") if rng else "0.5"
    msg = f"参数 {name} 的值不合法：{why}" + (f"（允许 {rng}{'，整数' if integral else ''}）" if rng else "")
    return LinkError("invalid_param", msg, f"填一个{'整数' if integral else '十进制数'}，例如 {eg}" + (f"，范围 {rng}" if rng else ""),
                     "params", {"message_zh": msg, "name": name, "reason": why, "example": eg,
                                **({"reject": code} if code else {})})


def check_value(name: str, raw, p: dict | None = None) -> float:
    """把界面 / Agent 给的值转成数：只收十进制数（int/float 或数字字符串）。
    拒绝：None、空串、'abc'、'0x10'、'1,5'、布尔、NaN、±Inf、越界、整数参数给小数。"""
    import math
    if isinstance(raw, bool) or raw is None:
        raise _invalid(name, "不是数字", p)
    if isinstance(raw, (int, float)):
        v = float(raw)
    elif isinstance(raw, str):
        t = raw.strip()
        if not t or any(c in t for c in ",，xX_"):
            raise _invalid(name, "不是十进制数", p)
        if not t.isascii():                                   # #60：float() 收全角/其他文字的数字（'１'、'٣'），这里一律拒
            raise _invalid(name, "含全角或非 ASCII 字符，只收半角数字", p)
        try:
            v = float(t)
        except ValueError:
            raise _invalid(name, "不是十进制数", p) from None
    else:
        raise _invalid(name, "不是数字", p)
    if math.isnan(v) or math.isinf(v):
        raise _invalid(name, "NaN / 无穷大不能写入", p)
    if p:
        if p.get("type", "f32") != "f32" and v != round(v):
            raise _invalid(name, "这个参数只能是整数", p)
        if "min" in p and "max" in p and not p["min"] <= v <= p["max"]:
            raise _invalid(name, "超出范围", p)
    return v
