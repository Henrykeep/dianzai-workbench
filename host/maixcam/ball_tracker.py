"""自写钢珠跟踪器（纯 Python，PC 上可测；相机上用 maix.image 的 find_blobs 提供候选）。

思路：
  1. 候选：每帧颜色阈值找色块（find_blobs），只在预测位置附近的 ROI 里找；连续丢 reacquire_after 帧后改为全画面搜索。
  2. 打分：离预测位置的距离（主要依据）+ 面积与上一帧的差异 + 外接框长宽比（钢珠应接近 1）。
     硬门限之外的候选（太远、太小、面积突变 3 倍以上、长宽比太离谱）直接丢弃，防止被反光、手、线缆抢走。
  3. 平滑与预测：α-β（与 firmware/algo/abobs 同一公式），漏检时外推，最多外推 max_coast 帧，
     期间置 predicted 标志，主控据此进入 HELD 状态。
  4. 锁定确认：搜索期需连续 N 帧位置一致才输出；门限随速度放宽；外推时速度逐帧衰减。
输出 TrackResult(x, y, detected, predicted)，x/y 以画面中心为原点（px）。
【已实测】PC 合成数据：test_ball_tracker.py。【未验证】实机阈值和帧率。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Blob:
    cx: float
    cy: float
    w: float
    h: float
    pixels: float


@dataclass
class TrackResult:
    x: float | None
    y: float | None
    detected: bool
    predicted: bool


class BallTracker:
    def __init__(self, width=320, height=240, alpha=0.6, beta=0.2, gate_px=60.0, roi_px=80,
                 min_pixels=12, max_aspect=2.2, max_coast=4, reacquire_after=6,
                 confirm=3, confirm_px=25.0, coast_damp=0.7, gate_vel_k=1.0, max_speed=80.0):
        # confirm：搜索模式下要连续 confirm 帧、相邻位移 < confirm_px 才算锁定（防单帧反光被当成球）；1 = 关闭
        # coast_damp：外推时每帧速度乘这个系数（防止丢球后越推越远）；1 = 不衰减
        # gate_vel_k：门限 += k·|v|（球快时预测误差大）；max_speed：速度上限 px/帧
        self.W, self.H = width, height
        self.alpha, self.beta = alpha, beta
        self.gate, self.roi_px = gate_px, roi_px
        self.min_pixels, self.max_aspect = min_pixels, max_aspect
        self.max_coast, self.reacquire_after = max_coast, reacquire_after
        self.confirm, self.confirm_px = max(1, confirm), confirm_px
        self.coast_damp, self.gate_vel_k, self.max_speed = coast_damp, gate_vel_k, max_speed
        self.reset()

    def reset(self):
        self.x = self.y = None          # 画面坐标（左上原点）
        self.vx = self.vy = 0.0
        self.area = None
        self.miss = 10 ** 6
        self.cand = []                  # 搜索期的候选轨迹（待确认）

    # ---- 给相机端用：本帧该在哪个 ROI 里找 ----
    def roi(self):
        if self.x is None or self.miss >= self.reacquire_after:
            return [0, 0, self.W, self.H]
        px, py = self.x + self.vx, self.y + self.vy
        r = self.roi_px
        x0, y0 = max(0, int(px - r)), max(0, int(py - r))
        return [x0, y0, min(self.W, int(px + r)) - x0, min(self.H, int(py + r)) - y0]

    def _score(self, b: Blob, px, py):
        if b.pixels < self.min_pixels:
            return None
        asp = max(b.w, b.h) / max(1.0, min(b.w, b.h))
        if asp > self.max_aspect:
            return None
        if px is None:                                   # 搜索模式：挑最大、最圆的
            return -b.pixels / asp
        d = math.hypot(b.cx - px, b.cy - py)
        gate = self.gate * (1 + 0.5 * min(self.miss, self.max_coast)) + self.gate_vel_k * math.hypot(self.vx, self.vy)
        if d > gate:                                     # 外推越久、球越快，门限越宽
            return None
        if self.area and not (self.area / 3 <= b.pixels <= self.area * 3):  # 面积突变（反光、手）硬淘汰
            return None
        size = abs(b.pixels - self.area) / max(self.area, 1.0) if self.area else 0.0
        return d + 20.0 * size + 5.0 * (asp - 1.0)

    def update(self, blobs) -> TrackResult:
        searching = self.x is None or self.miss >= self.reacquire_after
        px = None if searching else self.x + self.vx
        py = None if searching else self.y + self.vy
        best, best_s = None, None
        for b in blobs:
            s = self._score(b, px, py)
            if s is not None and (best_s is None or s < best_s):
                best, best_s = b, s
        if best is not None and searching and self.confirm > 1:
            if self.cand and math.hypot(best.cx - self.cand[-1].cx, best.cy - self.cand[-1].cy) > self.confirm_px:
                self.cand = []
            self.cand.append(best)
            if len(self.cand) < self.confirm:            # 还没确认：不输出、不动状态
                self.miss += 1
                return TrackResult(None, None, False, False)
        elif searching:
            self.cand = []
        if best is not None:
            if searching:
                c = self.cand
                self.x, self.y = best.cx, best.cy
                if len(c) >= 2:                          # 用确认期的位移给初速度
                    self.vx, self.vy = (c[-1].cx - c[0].cx) / (len(c) - 1), (c[-1].cy - c[0].cy) / (len(c) - 1)
                else:
                    self.vx = self.vy = 0.0
                self.cand = []
            else:
                rx, ry = best.cx - px, best.cy - py
                self.x, self.y = px + self.alpha * rx, py + self.alpha * ry
                self.vx += self.beta * rx
                self.vy += self.beta * ry
            sp = math.hypot(self.vx, self.vy)
            if sp > self.max_speed:
                self.vx, self.vy = self.vx * self.max_speed / sp, self.vy * self.max_speed / sp
            self.area = best.pixels if self.area is None else 0.7 * self.area + 0.3 * best.pixels
            self.miss = 0
            return TrackResult(self.x - self.W / 2, self.y - self.H / 2, True, False)
        self.miss += 1
        if self.x is not None and self.miss <= self.max_coast:
            self.x, self.y = self.x + self.vx, self.y + self.vy
            self.vx *= self.coast_damp
            self.vy *= self.coast_damp
            return TrackResult(self.x - self.W / 2, self.y - self.H / 2, False, True)
        self.vx = self.vy = 0.0
        return TrackResult(None, None, False, False)


def blobs_from_maix(maix_blobs):
    """maix.image.Blob → Blob。方法名按 MaixPy v4 文档（cx/cy/w/h/pixels）【未验证】。"""
    return [Blob(b.cx(), b.cy(), b.w(), b.h(), b.pixels()) for b in maix_blobs]
