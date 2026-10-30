"""日志导入 / 导出（缺口 13）：CSV、VOFA+ FireWater 进来转 .dzlog 能回放，出去能再读回。"""
import csv
import math
import time

import pytest

from dzbench import logio
from dzbench.export import dzlog_to_csv
from dzbench.session import Session
from dzbench.textparse import KvParser


def test_parse_csv_with_units_text_and_ms(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("\ufefft_s,speed[rpm],角度,state_txt\n0.00,1.5,10,RUN\n0.01,2.5,,RUN\n0.02,3,12,STOP\n", encoding="utf-8")
    names, rows, fmt = logio.parse(p)
    assert fmt == "csv" and names == ["speed", "角度"]                    # 单位去掉，文字列跳过
    assert rows[1][0] == pytest.approx(0.01) and math.isnan(rows[1][1][1])
    q = tmp_path / "b.csv"
    q.write_text("timestamp,x\n1700000000000,1\n1700000000010,2\n1700000000020,3\n")
    _, rows, _ = logio.parse(q)
    assert [round(t, 3) for t, _ in rows] == [0, 0.01, 0.02]              # 毫秒时间戳 → 从 0 开始的秒


def test_parse_vofa_firewater(tmp_path):
    p = tmp_path / "v.txt"
    p.write_text("boot ok\nsamples:1,2,3\n4.5,-5,6e1\n7,8\n", encoding="utf-8")
    names, rows, fmt = logio.parse(p, period_ms=5)
    assert fmt == "vofa" and names == ["ch1", "ch2", "ch3"]
    assert [v for _, v in rows][1] == [4.5, -5.0, 60.0] and rows[2][0] == pytest.approx(0.01) and math.isnan(rows[2][1][2])
    k = KvParser()                                                          # 实时串口也认 FireWater
    got, grew = k.feed(b"1.5,2\r\nx=3\n")
    assert grew and got == [{"ch1": 1.5, "ch2": 2.0}, {"x": 3.0}]
    with pytest.raises(logio.ImportError_):
        (tmp_path / "e.csv").write_text("a,b\nfoo,bar\n"); logio.parse(tmp_path / "e.csv")


def test_import_replay_and_export_roundtrip(tmp_path):
    src = tmp_path / "rec.csv"
    with open(src, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time", "yaw", "speed"])
        for i in range(50):
            w.writerow([f"{i * 0.02:.2f}", i, i * 0.5])
    r = logio.import_to_dzlog(src, tmp_path / "logs")
    assert r["rows"] == 50 and r["channels"] == ["yaw", "speed"] and r["seconds"] == pytest.approx(0.98)
    out = dzlog_to_csv(r["path"])                                           # 没 schema 的记录也能导出
    rows = list(csv.reader(open(out["path"], encoding="utf-8-sig")))
    assert rows[0] == ["t_s", "yaw", "speed"] and rows[-1] == ["0.9800", "49.0", "24.5"]
    v = dzlog_to_csv(r["path"], fmt="vofa")
    lines = open(v["path"]).read().splitlines()
    assert v["channels"] == ["yaw", "speed"] and lines[3] == "3.0,1.5" and len(lines) == 50
    back = logio.parse(v["path"], period_ms=20)                             # VOFA 导出再导入
    assert back[1][49][1] == [49.0, 24.5]
    s = Session()
    s.connect("replay:" + r["path"], log=False)
    s.replay_ctl(speed=20.0)
    for _ in range(50):
        if len(s.kv.names) == 2:
            break
        time.sleep(0.05)
    assert s.kv.names == ["yaw", "speed"]
    s.disconnect()
