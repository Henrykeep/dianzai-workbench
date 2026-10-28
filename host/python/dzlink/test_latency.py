"""latency 工具的纯计算部分。"""
from .latency import StreamStats, step_latencies, pct
from . import protocol as P
from .latency import _frames, BALL_FIELDS
from .transport import LoopbackTransport

s = StreamStats()
lat = [20, 35, 20, 28, 22, 24]
seqs = [250, 251, 252, 255, 0, 1]           # 253、254 丢失，跨 255→0 回绕
for i, (q, l) in enumerate(zip(seqs, lat)):
    s.feed(q, 5000 + i * 33, 100 + i * 33 + l)
s.feed(1, 0, 0)                             # 重复 seq 忽略
r = s.report()
assert r["frames"] == 6 and r["drops"] == 2, r
assert r["jitter_p50_ms"] == 2 and r["jitter_p95_ms"] == 15, r
assert abs(r["fps"] - 1000 / 33.8) < 0.1, r

flips = [(1000, 1), (2000, -1), (3000, 1)]
samples = [(1010, -50), (1060, -40), (1075, 60), (2000, 60), (2090, -55), (3050, None), (3200, -10)]
assert step_latencies(flips, samples) == [75, 90, None]
assert pct([5, 1, 3], 0.5) == 3

t = LoopbackTransport()
t.write(P.encode(P.DATA, 1, 7, P.pack_fields(BALL_FIELDS, {"flags": 9, "x_px": -3, "cam_ms": 42})))
got = list(_frames(t, P.Parser()))
assert got == [(7, {"flags": 9, "x_px": -3, "cam_ms": 42})], got
print("latency 自测通过")
