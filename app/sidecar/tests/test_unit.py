import json
import struct

from dzbench import downsample, logfile, snapshots
from dzbench._dzlink import DATA, HEARTBEAT, PARAM_ACK, encode
from dzbench.schema import Schema
from dzbench.session import Session
from dzbench.transport import LoopbackTransport

SCHEMA = {"version": 1, "hash": 0x12345678,
          "telemetry": {"id": 2, "period_ms": 20, "fields": [{"name": "t_ms", "type": "u32"}, {"name": "x", "type": "f32"},
                                                              {"name": "s", "type": "i16"}]},
          "params": [{"name": "kp", "type": "f32", "min": 0, "max": 2, "default": 0.5},
                     {"name": "n", "type": "u16", "min": 1, "max": 10, "default": 3}]}


def test_schema_decode_clamp():
    s = Schema(SCHEMA)
    assert s.size == 10
    assert s.decode(struct.pack("<Ifh", 1000, 1.5, -3)) == {"t_ms": 1000, "x": 1.5, "s": -3}
    assert s.decode(b"\0" * 9) is None
    assert s.clamp("kp", 5) == (2, True)
    assert s.clamp("n", 3.6) == (4.0, True)
    assert s.clamp("kp", 1.0) == (1.0, False)


def test_downsample_keeps_peaks():
    t = list(range(10000))
    y = [0.0] * 10000
    y[4321] = 99.0
    y[777] = -5.0
    tt, ys = downsample.minmax(t, {"y": y}, 200)
    assert len(tt) <= 200 and max(ys["y"]) == 99.0 and min(ys["y"]) == -5.0
    assert downsample.minmax([1, 2], {"y": [3, 4]}, 200) == ([1, 2], {"y": [3, 4]})


def test_log_roundtrip_and_truncated(tmp_path):
    p = tmp_path / "a.dzlog"
    w = logfile.LogWriter(p, {"port": "x"})
    w.write(logfile.RX, b"abc")
    w.write(logfile.TX, b"\x01\x02")
    w.close()
    with open(p, "ab") as f:
        f.write(logfile.REC.pack(9.0, 0, 100) + b"short")   # 崩溃留下的半条
    h, recs = logfile.read_log(p)
    assert h == {"port": "x"} and [(d, b) for _, d, b in recs] == [(0, b"abc"), (1, b"\x01\x02")]


def test_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path))
    snapshots.save(1, "决赛 版/1", {"kp": 1.0})
    (only,) = snapshots.list_all(1)
    assert only["name"] == "决赛_版_1" and snapshots.load(1, only["name"]) == {"kp": 1.0}
    assert snapshots.list_all(2) == []


def test_session_loopback(tmp_path, monkeypatch):
    sdir = tmp_path / "build" / "x" / "linkgen"
    sdir.mkdir(parents=True)
    (sdir / "link_schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    monkeypatch.setenv("DZBENCH_SCHEMA_DIRS", str(tmp_path / "build"))
    ev = []
    s = Session(emit=ev.append, log_dir=tmp_path / "logs")
    lb = LoopbackTransport()
    s.tr = lb
    lb.start(s._on_bytes, lambda m: None)
    lb.feed(encode(HEARTBEAT, 0, 0, struct.pack("<I", 0x12345678)) + encode(DATA, 2, 1, struct.pack("<Ifh", 20, 0.25, 7)))
    import time
    for _ in range(50):
        if s.samples:
            break
        time.sleep(0.01)
    assert s.schema and s.window(1)[-1] == (0.02, {"t_ms": 20, "x": 0.25, "s": 7})
    lb.feed(encode(PARAM_ACK, 0, 2, struct.pack("<Bf", 1, 2.0)))
    time.sleep(0.05)
    assert s.params["kp"] == 2.0
    assert any(e["type"] == "param" and e["status"] == "clamped" for e in ev)
    s.disconnect()


def test_estop_when_disconnected_is_honest():
    r = Session().estop()
    assert r["ok"] is False and r["reason"] == "no_board" and "没有送达" in r["message_zh"]
    assert set(r) == Session.ESTOP_REPLY_KEYS                 # 精确等于约定：没有 sent / message / nolink / src


def test_unknown_schema_gives_fix(tmp_path, monkeypatch):
    monkeypatch.setenv("DZBENCH_SCHEMA_DIRS", str(tmp_path))
    ev = []
    s = Session(emit=ev.append)
    s._bind_schema(0xDEADBEEF)
    (e,) = [x for x in ev if x["type"] == "error"]
    assert e["code"] == "schema_missing" and "make" in e["fix"]


def test_read_all_params_bg_swallows_thread_exception():
    """v0.6.0：后台读参途中串口被关（_send 抛 OSError）不能变成未处理线程异常。"""
    import threading
    from dzbench.session import Session

    ev = []
    s = Session(emit=ev.append)

    class FakeSchema:
        params = [{"name": "kp"}]
        param_index = {"kp": 0}
    s.schema = FakeSchema()

    def boom(*a, **k):
        raise OSError("port closed")
    s._send = boom
    caught = []
    old = threading.excepthook
    threading.excepthook = lambda a: caught.append(a)
    try:
        t = threading.Thread(target=s._read_all_params_bg)
        t.start()
        t.join(2)
    finally:
        threading.excepthook = old
    assert not caught
    assert any(e.get("code") == "param_read_aborted" for e in ev if isinstance(e, dict)), ev


def test_estop_without_board_does_not_latch_or_alert():
    """仿真板一连上就看到锁存急停的根因：没连板子时按 Esc（关下拉框）也锁住侧车并进告警条。"""
    from dzbench.events import from_broadcast
    s = Session()
    r = s.estop("Esc 键")
    assert r["reason"] == "no_board" and "Esc 键" in r["message_zh"] and s.tx_locked is False
    assert from_broadcast(r) is None
    kind, text, source = from_broadcast({"type": "estop", "sent": True, "src": "急停按钮"})
    assert source == "ui"
    assert kind == "estop" and "急停按钮" in text and "解除急停 R" in text


def test_estop_cause_fields():
    """dzctl 0.8.0 心跳尾部 cause/t_ms/value → 前端用的结构化字段。"""
    from dzbench.session import estop_cause_dict
    assert estop_cause_dict(0, 0, 0.0) is None
    d = estop_cause_dict(2, 12345, 1180.0)
    assert d["cause"] == "hb_timeout" and d["cause_id"] == 2 and d["t"] == 12.345 and d["value"] == 1180.0
    assert d["message_zh"].startswith("心跳超时：上位机 1180 ms 未发送心跳")
    assert "6.10 V" in estop_cause_dict(4, 0, 6.1)["message_zh"]
    assert "看门狗" in estop_cause_dict(8, 0, 4.0)["message_zh"]
    assert estop_cause_dict(42, 0, 0.0)["cause"] == "unknown_42"


def test_estop_reply_contract_documented():
    import pathlib
    doc = (pathlib.Path(__file__).resolve().parents[3] / "docs/dev/events.md").read_text(encoding="utf-8")
    for k in Session.ESTOP_REPLY_KEYS | {"no_board", "replay"}:
        assert f"`{k}`" in doc, k
