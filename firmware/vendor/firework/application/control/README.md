# Control Application

本目录用于保存舵机、电机等执行机构的 Application 层控制逻辑，例如目标值管理、
运行状态机、闭环控制流程、故障处理以及控制任务的业务循环。

当前目录结构：

```text
control/
├── servo_control/       PA23/PA24 双路舵机角度和动作控制任务
└── motor_control/       TB6612 双路直流电机平滑调速和安全停机任务
```

## 分层约束

- `control/` 只负责产品控制策略和任务业务逻辑。
- PWM、GPIO、编码器、ADC 等硬件访问应通过 `modules/`，不得直接调用 TI DriverLib。
- 任务名称、优先级、静态 TCB、静态栈和创建入口统一登记到
  [`../task/task_manager.c`](../task/task_manager.c)。
- 具体任务循环保留在对应的 `servo_control/` 或 `motor_control/` 业务文件中。
- 初始化失败、通信失联或控制数据无效时，应停止执行机构并进入安全状态。

现有舵机任务的接口、接线和配置方法见
[`servo_control/舵机控制任务使用指南.md`](servo_control/舵机控制任务使用指南.md)。
TB6612 电机任务见
[`motor_control/电机控制任务使用指南.md`](motor_control/电机控制任务使用指南.md)。

## 添加控制任务

新增舵机或电机控制任务时，应依次完成：

1. 在本目录建立对应的控制 Application，并实现初始化函数和任务循环。
2. 在 `application/app_config.h` 中增加功能编译开关和依赖检查。
3. 在 `ApplicationTask_e` 中登记任务编号，并在 Task Manager 中配置任务资源。
4. 在 `ApplicationInit()` 中完成 Module 初始化和任务创建。
5. 在 `ApplicationEnterSafeState()` 中加入执行机构的安全停止操作。

控制任务应优先使用 `vTaskDelayUntil()` 保持固定周期，或使用任务通知、Queue、
Semaphore 等机制等待事件，避免无阻塞的忙循环。
