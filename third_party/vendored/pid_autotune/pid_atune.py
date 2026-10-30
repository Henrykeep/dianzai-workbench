"""继电反馈 PID 自整定（PID_ATune 的 Python 移植）。
Source: github.com/br3ttb/Arduino-PID-AutoTune-Library@7c03cf3 PID_AutoTune_v0/PID_AutoTune_v0.cpp
BSD License, Copyright (c) Brett Beauregard / William Spinelli 2004（见同目录 LICENSE）。改动见 SOURCE.md。
"""
from __future__ import annotations

import math


class PIDATune:
    def __init__(self, *, output_step: float = 30.0, noise_band: float = 0.5, lookback_s: float = 10.0,
                 control_type: int = 0, sample_time: float | None = None):
        self.o_step, self.noise_band, self.control_type = output_step, noise_band, control_type
        if sample_time is None:                      # 原版 SetLookbackSec：<25 s 时 250 ms 采样、4 点/秒
            lb = max(1, int(lookback_s))
            self.n_lookback, self.sample_time = (lb * 4, 0.25) if lb < 25 else (100, lb * 0.01)
        else:
            self.sample_time = sample_time
            self.n_lookback = max(3, min(100, int(round(lookback_s / sample_time))))
        self.running, self.last_t = False, None
        self.ku = self.pu = None

    def runtime(self, t: float, y: float, u_now: float) -> tuple[bool, float]:
        """每拍调用。返回 (done, 输出)。done=True 后 ku/pu/gains() 可用，输出回到起始值。"""
        if self.running and self.peak_count > 9:
            self.running = False
            self._finish()
            return True, self.output_start
        if self.last_t is not None and t - self.last_t < self.sample_time:
            return False, self.u
        self.last_t = t
        if not self.running:
            self.peak_type, self.peak_count, self.just_changed = 0, 0, False
            self.abs_max = self.abs_min = y
            self.setpoint, self.running = y, True
            self.output_start = u_now
            self.u = u_now + self.o_step
            self.last_inputs, self.peaks = [], [0.0] * 11
            self.peak1 = self.peak2 = t
        else:
            self.abs_max, self.abs_min = max(self.abs_max, y), min(self.abs_min, y)
        if y > self.setpoint + self.noise_band:
            self.u = self.output_start - self.o_step
        elif y < self.setpoint - self.noise_band:
            self.u = self.output_start + self.o_step
        hist = self.last_inputs
        is_max = bool(hist) and all(y > v for v in hist)
        is_min = bool(hist) and all(y < v for v in hist)
        hist.insert(0, y)
        del hist[self.n_lookback:]
        if len(hist) < self.n_lookback:
            return False, self.u
        if is_max:
            if self.peak_type == -1:
                self.just_changed, self.peak2 = True, self.peak1
            self.peak_type = 1
            self.peak1 = t
            self.peaks[self.peak_count] = y
        elif is_min:
            if self.peak_type == 1:
                self.peak_count += 1
                self.just_changed = True
            self.peak_type = -1
            if self.peak_count < 10:
                self.peaks[self.peak_count] = y
        if self.just_changed and self.peak_count > 2:
            p = self.peaks
            sep = (abs(p[self.peak_count - 1] - p[self.peak_count - 2]) + abs(p[self.peak_count - 2] - p[self.peak_count - 3])) / 2
            if sep < 0.05 * (self.abs_max - self.abs_min):
                self.running = False
                self._finish()
                return True, self.output_start
        self.just_changed = False
        return False, self.u

    def _finish(self):
        amp = max(self.abs_max - self.abs_min, 1e-12)
        self.ku = 4 * (2 * self.o_step) / (amp * math.pi)
        self.pu = max(self.peak1 - self.peak2, 1e-9)

    def gains(self) -> dict:
        ku, pu = self.ku, self.pu
        if self.control_type == 1:
            return {"kp": 0.6 * ku, "ki": 1.2 * ku / pu, "kd": 0.075 * ku * pu}
        return {"kp": 0.4 * ku, "ki": 0.48 * ku / pu, "kd": 0.0}
