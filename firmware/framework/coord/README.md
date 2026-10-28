# 顶层协调状态机  `v1.1.0`

IDLE/RUNNING/DONE/ESTOP/FAULT；管测试项、参数档、启停、急停（必须 RESET 才能再启动）、限时；pre_step 钩子做跨子系统前馈。与题目无关。

- 接口：`coord_init/select_test/select_profile/event/poll`
- 自检：`coord_selftest()`（v1.1.0 新增）；tests/host/test_framework.c
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：状态转换与限时主机单测
- **未验证**：—

## 参考来源
- UML 状态机；电赛测试流程（小题号 + 限时）
