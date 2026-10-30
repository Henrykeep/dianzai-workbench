""".dzlog → CSV：离线按 schema 解码遥测，UTF-8 BOM（Excel 双击直接打开中文不乱码），逗号分隔。
思路参考 SerialWeb（导出带 BOM 的 CSV）；代码自写。
fmt="vofa"：VOFA+ FireWater 文本（每样本一行逗号分隔数值，无表头）。文本遥测 / 导入的记录没有 schema 时按 key=value 解出来导出。
fmt="plotjuggler"：无 BOM、时间列叫 time、只有数值列（枚举给数字），PlotJuggler 的 CSV 加载器打开后选 time 作时间轴即可。
列：t_s（板端 t_ms/1000，没有就用记录时间）、各遥测字段；枚举字段额外给一列文字（如 state_txt）。
"""
from __future__ import annotations

import csv
import pathlib
import struct

from ._dzlink import DATA, HEARTBEAT, Parser
from .logfile import RX, read_log
from .schema import Schema, find_by_hash
from .textparse import KvParser


class ExportError(Exception):
    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.message, self.fix = message, fix


def dzlog_to_csv(path, out=None, schema: Schema | None = None, fmt: str = "excel") -> dict:
    pj, vofa = fmt == "plotjuggler", fmt == "vofa"
    path = pathlib.Path(path)
    header, recs = read_log(path)
    p = Parser()
    rows, hb_hash = [], None
    kv, kv_rows = KvParser(), None
    if not header.get("schema_hash"):                                # 文本遥测 / 导入的记录：没 schema 也能导出
        kv_rows = ([], [])
    if schema is None and header.get("schema_hash"):
        schema = find_by_hash(int(header["schema_hash"], 16))
    for t_rec, d, b in recs:
        if d != RX:
            continue
        if kv_rows is not None and schema is None:
            got, _ = kv.feed(b)
            for v in got:
                kv_rows[1].append((t_rec, v))
            kv_rows = (kv.names, kv_rows[1])
        for kind, id_, _seq, payload in p.feed(b):
            if kind == HEARTBEAT and len(payload) >= 4 and schema is None:
                hb_hash = struct.unpack_from("<I", payload)[0]
                schema = find_by_hash(hb_hash)
            elif kind == DATA and schema and id_ == schema.telem_id:
                v = schema.decode(payload)
                if v is not None:
                    rows.append((v["t_ms"] / 1000.0 if "t_ms" in v else t_rec, v))
    if schema is None and kv_rows is not None and kv_rows[1]:
        return _write_kv(path, out, kv_rows, fmt)
    if schema is None:
        h = header.get("schema_hash") or (f"{hb_hash:08X}" if hb_hash is not None else "未知")
        raise ExportError(f"找不到这份记录的数据格式（schema {h}）", "先连一次对应固件的板子（会缓存 schema），或把 link_schema.json 放进 ~/.dzbench/schemas")
    fields = [f for f in schema.fields if f["name"] != "t_ms"]
    enums = [f for f in fields if f.get("enum")]
    if pj:
        enums = []
    out = pathlib.Path(out) if out else path.with_suffix(".pj.csv" if pj else ".vofa.txt" if vofa else ".csv")
    if vofa:
        return _write_vofa(out, [f["name"] for f in fields], [(t, [v[f["name"]] for f in fields]) for t, v in rows], p.bad)
    with open(out, "w", newline="", encoding="utf-8" if pj else "utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["time" if pj else "t_s"] + [f["name"] + (f"[{f['unit']}]" if f.get("unit") else "") for f in fields] + [f["name"] + "_txt" for f in enums])
        for t, v in rows:
            row = [f"{t:.4f}"] + [_num(v[f["name"]]) for f in fields]
            for f in enums:
                i = int(v[f["name"]])
                row.append(f["enum"][i] if 0 <= i < len(f["enum"]) else "")
            w.writerow(row)
    return {"path": str(out), "rows": len(rows), "columns": 1 + len(fields) + len(enums), "bad_frames": p.bad, "fmt": "plotjuggler" if pj else "excel"}


def _write_vofa(out, names, rows, bad=0) -> dict:
    """VOFA+ FireWater：每样本一行 `v1,v2,…\n`，无表头（VOFA+ 按顺序叫 I1、I2…；列顺序见返回的 channels）。"""
    with open(out, "w", newline="", encoding="utf-8") as fh:
        for _t, vals in rows:
            fh.write(",".join(_num(x) for x in vals) + "\n")
    return {"path": str(out), "rows": len(rows), "columns": len(names), "channels": names, "bad_frames": bad, "fmt": "vofa"}


def _write_kv(path, out, kv_rows, fmt) -> dict:
    names, rows = kv_rows
    nan = float("nan")
    full = [(t, [v.get(n, nan) for n in names]) for t, v in rows]
    vofa, pj = fmt == "vofa", fmt == "plotjuggler"
    out = pathlib.Path(out) if out else path.with_suffix(".pj.csv" if pj else ".vofa.txt" if vofa else ".csv")
    if vofa:
        return _write_vofa(out, names, full)
    t0 = full[0][0]
    with open(out, "w", newline="", encoding="utf-8" if pj else "utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["time" if pj else "t_s"] + names)
        for t, vals in full:
            w.writerow([f"{t - t0:.4f}"] + ["" if x != x else _num(x) for x in vals])
    return {"path": str(out), "rows": len(full), "columns": 1 + len(names), "bad_frames": 0, "fmt": fmt}


def _num(x) -> str:
    return repr(float(x)) if isinstance(x, float) else str(x)
