""".dzlog → CSV：离线按 schema 解码遥测，UTF-8 BOM（Excel 双击直接打开中文不乱码），逗号分隔。
思路参考 SerialWeb（导出带 BOM 的 CSV）；代码自写。
列：t_s（板端 t_ms/1000，没有就用记录时间）、各遥测字段；枚举字段额外给一列文字（如 state_txt）。
"""
from __future__ import annotations

import csv
import pathlib
import struct

from ._dzlink import DATA, HEARTBEAT, Parser
from .logfile import RX, read_log
from .schema import Schema, find_by_hash


class ExportError(Exception):
    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.message, self.fix = message, fix


def dzlog_to_csv(path, out=None, schema: Schema | None = None) -> dict:
    path = pathlib.Path(path)
    header, recs = read_log(path)
    p = Parser()
    rows, hb_hash = [], None
    if schema is None and header.get("schema_hash"):
        schema = find_by_hash(int(header["schema_hash"], 16))
    for t_rec, d, b in recs:
        if d != RX:
            continue
        for kind, id_, _seq, payload in p.feed(b):
            if kind == HEARTBEAT and len(payload) >= 4 and schema is None:
                hb_hash = struct.unpack_from("<I", payload)[0]
                schema = find_by_hash(hb_hash)
            elif kind == DATA and schema and id_ == schema.telem_id:
                v = schema.decode(payload)
                if v is not None:
                    rows.append((v["t_ms"] / 1000.0 if "t_ms" in v else t_rec, v))
    if schema is None:
        h = header.get("schema_hash") or (f"{hb_hash:08X}" if hb_hash is not None else "未知")
        raise ExportError(f"找不到这份记录的数据格式（schema {h}）", "先连一次对应固件的板子（会缓存 schema），或把 link_schema.json 放进 ~/.dzbench/schemas")
    fields = [f for f in schema.fields if f["name"] != "t_ms"]
    enums = [f for f in fields if f.get("enum")]
    out = pathlib.Path(out) if out else path.with_suffix(".csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s"] + [f["name"] + (f"[{f['unit']}]" if f.get("unit") else "") for f in fields] + [f["name"] + "_txt" for f in enums])
        for t, v in rows:
            row = [f"{t:.4f}"] + [_num(v[f["name"]]) for f in fields]
            for f in enums:
                i = int(v[f["name"]])
                row.append(f["enum"][i] if 0 <= i < len(f["enum"]) else "")
            w.writerow(row)
    return {"path": str(out), "rows": len(rows), "columns": 1 + len(fields) + len(enums), "bad_frames": p.bad}


def _num(x) -> str:
    return repr(float(x)) if isinstance(x, float) else str(x)
