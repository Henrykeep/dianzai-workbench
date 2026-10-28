"""视觉链路延迟工具（自写）。

两种用法：
  python -m dzlink.latency stats --port COM5            # 只看相机串口：帧率、帧间隔 p50/p95、丢帧、相对延迟抖动
  python -m dzlink.latency flash --port COM5            # 测绝对延迟（屏幕闪点法）

flash 原理：电脑全屏黑底上的白点每 period 秒在左右两侧之间跳一次，相机对准屏幕运行 ball_sender.py。
从白点跳过去（主机时间 t0），到第一帧报告的 x 换号（主机收到时刻 t1），t1 − t0 就是
  显示器刷新/响应 + 曝光 + 识别 + 串口传输 + 主机读取
的总延迟。显示器本身有约 5~30 ms 的延迟，结果会偏大；要更准，可以用 MCU 的 LED 代替屏幕（思路相同）。
得到的中位数可以直接作为 ball_beam 超前量 bb_lead_s 的起点（再加上机械延迟）。
相机端的 BALL_LAB 阈值要能识别白点，或者临时改成白色阈值。
【已实测】PC 合成数据（test_latency.py）。【未验证】实机。
"""
from __future__ import annotations

import argparse
import statistics
import time

from . import protocol as P

BALL_ID = 1
BALL_FIELDS = [{"name": "flags", "type": "u8"}, {"name": "x_px", "type": "i16"}, {"name": "cam_ms", "type": "u32"}]


def pct(xs, q):
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


class StreamStats:
    """逐帧喂 (seq, cam_ms, host_ms)。"""

    def __init__(self):
        self.n = 0
        self.drops = 0
        self.last_seq = None
        self.last_host = None
        self.intervals = []
        self.offsets = []

    def feed(self, seq, cam_ms, host_ms):
        if self.last_seq is not None:
            gap = (seq - self.last_seq) & 0xFF
            if gap == 0:
                return
            if gap < 128:
                self.drops += gap - 1
        if self.last_host is not None:
            self.intervals.append(host_ms - self.last_host)
        self.last_seq, self.last_host = seq, host_ms
        self.offsets.append(host_ms - cam_ms)
        self.n += 1

    def report(self):
        mn = min(self.offsets) if self.offsets else 0.0
        jit = [o - mn for o in self.offsets]
        iv = self.intervals
        return {
            "frames": self.n, "drops": self.drops,
            "fps": 1000.0 / statistics.mean(iv) if iv else float("nan"),
            "interval_p50_ms": pct(iv, 0.5), "interval_p95_ms": pct(iv, 0.95), "interval_max_ms": max(iv) if iv else float("nan"),
            "jitter_p50_ms": pct(jit, 0.5), "jitter_p95_ms": pct(jit, 0.95),
        }


def step_latencies(flips, samples):
    """flips: [(host_ms, side)]，side = +1/−1；samples: [(host_ms, x 或 None)]，按时间排序。
    每次翻转后第一帧 sign(x) == side 的时刻减去翻转时刻。下一次翻转前都没看到就记 None。"""
    out = []
    for i, (t0, side) in enumerate(flips):
        t_end = flips[i + 1][0] if i + 1 < len(flips) else float("inf")
        hit = next((t for t, x in samples if t0 <= t < t_end and x is not None and x * side > 0), None)
        out.append(None if hit is None else hit - t0)
    return out


def _frames(transport, parser):
    for kind, id_, seq, payload in parser.feed(transport.read()):
        if kind == P.DATA and id_ == BALL_ID and len(payload) == 7:
            yield seq, P.unpack_fields(BALL_FIELDS, payload)


def cmd_stats(a, transport):
    st, parser = StreamStats(), P.Parser()
    t_end = time.monotonic() + a.seconds
    while time.monotonic() < t_end:
        for seq, v in _frames(transport, parser):
            st.feed(seq, v["cam_ms"], time.monotonic() * 1000)
        time.sleep(0.001)
    for k, v in st.report().items():
        print(f"{k:18s} {v:.1f}" if isinstance(v, float) else f"{k:18s} {v}")


def cmd_flash(a, transport):
    import tkinter as tk
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.configure(bg="black")
    cv = tk.Canvas(root, bg="black", highlightthickness=0)
    cv.pack(fill="both", expand=True)
    root.update()
    W, H = root.winfo_width(), root.winfo_height()
    r = a.dot
    dot = cv.create_oval(0, 0, 0, 0, fill="white", outline="")
    flips, samples, parser = [], [], P.Parser()
    side = -1
    t_next = time.monotonic()
    t_end = t_next + a.seconds
    while time.monotonic() < t_end:
        now = time.monotonic()
        if now >= t_next:
            side = -side
            cx = W / 2 + side * W / 4
            cv.coords(dot, cx - r, H / 2 - r, cx + r, H / 2 + r)
            root.update()                                    # 提交绘制后再打时间戳
            flips.append((time.monotonic() * 1000, side * a.sign))
            t_next = now + a.period
        for _, v in _frames(transport, parser):
            samples.append((time.monotonic() * 1000, v["x_px"] if v["flags"] & 0x08 else None))
        root.update()
        time.sleep(0.001)
    root.destroy()
    lat = [x for x in step_latencies(flips, samples) if x is not None]
    miss = len(flips) - len(lat)
    if not lat:
        print("一次都没看到换边：检查相机是否对准屏幕、阈值能否识别白点、--sign 是否反了")
        return
    print(f"翻转 {len(flips)} 次，有效 {len(lat)}，未识别 {miss}")
    print(f"延迟 p50 {pct(lat, .5):.0f} ms  p95 {pct(lat, .95):.0f} ms  min {min(lat):.0f}  max {max(lat):.0f}")
    print(f"建议 bb_lead_s 起点 ≈ {pct(lat, .5) / 1000:.3f} s（再加上摆杆机械延迟，显示器延迟会让结果偏大）")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m dzlink.latency")
    ap.add_argument("mode", choices=["stats", "flash"])
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--period", type=float, default=0.8, help="flash：白点跳变间隔 s")
    ap.add_argument("--dot", type=int, default=40, help="flash：白点半径 px")
    ap.add_argument("--sign", type=int, default=1, choices=[1, -1], help="flash：相机看到的左右与屏幕相反时用 −1")
    a = ap.parse_args(argv)
    from .transport import SerialTransport
    t = SerialTransport(a.port, a.baud)
    (cmd_stats if a.mode == "stats" else cmd_flash)(a, t)


if __name__ == "__main__":
    main()
