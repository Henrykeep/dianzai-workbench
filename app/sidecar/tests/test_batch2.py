"""频谱与可拖动回放（离线）。"""
import math
import struct
import time

from dzbench._dzlink import DATA, HEARTBEAT, encode
from dzbench.logfile import RX, LogWriter
from dzbench.replay import ReplayTransport
from dzbench.session import Session
from dzbench.spectrum import spectrum


def test_spectrum_peak_amplitude_and_dc_removed():
    t = [i * 0.01 for i in range(3000)]
    y = [10 + 1.5 * math.sin(2 * math.pi * 12.0 * x) + 0.5 * math.sin(2 * math.pi * 31.0 * x) for x in t]
    r = spectrum(t, y, 0.01)
    assert r["ok"] and r["n"] == 2048 and r["fs"] == 100
    p = r["peaks"]
    assert abs(p[0]["f"] - 12.0) < r["df"] and abs(p[0]["amp"] - 1.5) < 0.15
    assert abs(p[1]["f"] - 31.0) < r["df"] and abs(p[1]["amp"] - 0.5) < 0.08
    assert r["amp"][0] == 0 and r["amp"][1] < 0.05 and not r["warn"]


def test_spectrum_warns_on_period_mismatch_and_drops():
    t = [i * 0.04 for i in range(256)]
    assert "不符" in spectrum(t, [math.sin(x) for x in t], 0.02)["warn"]
    t = [i * 0.02 for i in range(256)]
    t = t[:100] + [x + 0.2 for x in t[100:]]
    assert "丢帧" in spectrum(t, [0.0] * 256, 0.02)["warn"]
    assert not spectrum([0, 1], [0, 1])["ok"]


def make_log(path, secs=2.0, dt=0.02):
    w = LogWriter(path, {"port": "x", "schema_hash": None})
    recs = []
    for i in range(int(secs / dt)):
        recs.append((i * dt, encode(DATA, 2, i & 0xFF, struct.pack("<I", i))))
    w.close()
    import pathlib
    from dzbench.logfile import MAGIC, REC
    import json
    raw = MAGIC + json.dumps({"port": "x"}).encode() + b"\n" + b"".join(REC.pack(t, RX, len(b)) + b for t, b in recs)
    pathlib.Path(path).write_bytes(raw)


def test_replay_seek_speed_pause(tmp_path):
    make_log(tmp_path / "r.dzlog")
    tr = ReplayTransport(tmp_path / "r.dzlog")
    assert abs(tr.duration - 1.98) < 1e-9
    tr.seek(1.5)
    got = []
    end = time.monotonic() + 0.3
    while time.monotonic() < end and len(got) < 3:
        b = tr.read()
        if b:
            got.append(b)
    from dzbench._dzlink import Parser
    fr = Parser().feed(b"".join(got))
    first = struct.unpack("<I", fr[0][3])[0] if fr else None
    assert first == 75, first                     # 1.5 s / 0.02
    tr.pause(True)
    p = tr.position(); time.sleep(0.1)
    assert tr.position() == p and tr.read() == b""
    tr.pause(False); tr.set_speed(10)
    time.sleep(0.05)
    assert tr.position() > p + 0.3
    tr.seek(99)
    assert tr.position() == tr.duration and tr.progress() == 1.0


def test_session_replay_ctl_clears_samples(tmp_path):
    make_log(tmp_path / "r.dzlog")
    s = Session()
    s.connect(f"replay:{tmp_path / 'r.dzlog'}")
    st = s.replay_ctl(seek=1.0, speed=2.0)
    assert st["speed"] == 2.0 and st["pos"] >= 1.0 and s.status()["replay_len"] > 1.9
    s.disconnect()
    try:
        s.replay_ctl(seek=0)
    except Exception as e:
        assert e.code == "not_replay"
