# 视觉链路与标定  `v1.1.0`

- `vis_link`：把视觉帧流变成 VALID / HELD / LOST 三态，同时给出数据时效 age_ms、丢帧数（8 位 seq 回绕）、相对延迟抖动。
- `vis_calib`：用 2..9 个点把像素换算成物理量（分段线性）。中心两侧各两点以上时，左右斜率互相独立。
- `vis_plane`（1.1.0）：平面五点标定。四个已知点（一般是屏幕/靶纸四角）求透视变换，第五点（中心）只做验收，`check_err` 超容差说明点错了或相机动了。双向：像素→平面、平面→像素（激光/云台打点）。
  斜看的屏幕上，只按两角线性插值中心点会错 48.6 mm（600 mm 屏，测试里的透视参数），单应误差 0.0002 mm。
- 自检：`vis_selftest()`；tests/host/test_vision.c

## 用法
```c
vis_link_feed(&vl, f.seq, b.cam_ms, pal_millis(), b.flags & 1, b.x_px);   // 收到一帧
switch (vis_link_poll(&vl, now)) { case VIS_VALID: ...; case VIS_HELD: /* 保持/预测 */; case VIS_LOST: /* 安全动作 */; }
```

## 验证状态
- **已实测（PC 主机）**：三态切换、seq 回绕与丢帧、延迟抖动窗口、标定插值与外推（tests/host/test_vision.c）
- **已实测（PC 主机，1.1.0）**：已知透视变换下 169 点网格误差 < 0.001 mm、往返 < 0.0001 px；中心点点错 8 px → check_err 22.9 mm；共线/NaN 拒绝（tests/host/test_ctrlparts.c）
- **[未测]**：实机相机链路、镜头畸变大时四点单应的残差（畸变要在协处理器端先校正）

## 参考来源
- 五点标定：2023 E 题常见做法是四角透视变换 + 中心点（github.com/DBinK/2023-NUEDC-E-OpenCV，Apache-2.0；oshwhub 2023 电赛 E 题方案，GPL-3.0，只读思路）。单应 DLT 公式见 Hartley & Zisserman《Multiple View Geometry》第 4 章。代码自写。
- 自写。HELD 保持一段时间再判 LOST 的做法属于常识；“最小单程差值”估延迟的思路来自 NTP 的最小延迟滤波。
