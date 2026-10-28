# 子系统接口与调度器  `v1.0.0`

子系统 = {name, period_ms, run_always, init, step, on_mode, selftest}，彼此不 include，只通过共享 state 结构体中自己拥有的段交换数据（check_deps S1/S2 强制）。调度器按周期轮询，回绕安全，统计 overrun。

- 接口：`subsys_sched_init/poll/set_mode/set_params/selftest`
- 自检：`subsys_sched_selftest()`；tests/host/test_framework.c
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：周期、模式、overrun、32 位时间回绕主机单测
- **未验证**：真实 MCU 上的时序抖动**未实测**

## 参考来源
- RoboMaster 开源步兵代码“任务 + 全局数据结构”的组织方式；协作式调度（cooperative scheduler）经典做法
