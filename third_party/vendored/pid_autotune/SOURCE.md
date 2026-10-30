# pid_autotune —— Arduino PID AutoTune（继电反馈自整定，BSD）

Source: github.com/br3ttb/Arduino-PID-AutoTune-Library@7c03cf3 PID_AutoTune_v0/PID_AutoTune_v0.cpp
（Brett Beauregard，移植自 William Spinelli 的 AutotunerPID Toolkit；许可 BSD，`LICENSE` 为原 README 头部原文）

- 搬了什么：PID_ATune 全部逻辑——继电输出 ±oStep、噪声带、lookback 峰值检测、峰值收敛（相邻峰差 < 5% 幅度）判停、
  Ku = 4·(2·oStep)/(π·幅度)、Pu = 峰间时间，PI(0.4Ku, 0.48Ku/Pu) / PID(0.6Ku, 1.2Ku/Pu, 0.075KuPu)。
- 改了什么：C++ → Python；millis() 改为调用方传入时间 t（秒），Pu 直接是秒；指针输入输出改为 runtime(t, y) 返回 (done, u)；
  原版 nLookBack<9 时也返回（原版的判断写反了，恒为假，这里保留“数组未填满不认峰”的本意：样本数 < nLookBack 时不认峰）；
  peaks[] 越界保护（原版 peakCount 到 10 时写越界）。
- 侧车只经 `app/sidecar/dzbench/tuning/relay.py` 调用。
