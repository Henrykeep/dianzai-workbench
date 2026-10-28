# 视觉链路与标定  `v1.0.0`

- `vis_link`：把视觉帧流变成 VALID / HELD / LOST 三态，同时给出数据时效 age_ms、丢帧数（8 位 seq 回绕）、相对延迟抖动。
- `vis_calib`：用 2..9 个点把像素换算成物理量（分段线性）。中心两侧各两点以上时，左右斜率互相独立。
- 自检：`vis_selftest()`；tests/host/test_vision.c

## 用法
```c
vis_link_feed(&vl, f.seq, b.cam_ms, pal_millis(), b.flags & 1, b.x_px);   // 收到一帧
switch (vis_link_poll(&vl, now)) { case VIS_VALID: ...; case VIS_HELD: /* 保持/预测 */; case VIS_LOST: /* 安全动作 */; }
```

## 验证状态
- **已实测（PC 主机）**：三态切换、seq 回绕与丢帧、延迟抖动窗口、标定插值与外推（tests/host/test_vision.c）
- **未验证**：实机相机链路

## 参考来源
- 自写。HELD 保持一段时间再判 LOST 的做法属于常识；“最小单程差值”估延迟的思路来自 NTP 的最小延迟滤波。
