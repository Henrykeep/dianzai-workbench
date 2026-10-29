# 否决：从 PID_Helper 借来的两个协议做法

- **8 位累加和校验**（PID_Helper `README.md:217` 帧 `AA 55 cmd seq a0 a1 a2 sum`）：电机驱动线上干扰大，累加和对双字节错误/字节交换检不出；dzframe 继续用 CRC。
- **协议层回调签名带 HAL 类型**（H7 例程 `User/pid_helper_protocol.h:65` `TxFn` 返回 `HAL_StatusTypeDef`）：会让协议层绑死 STM32，换 MSPM0 要重写；我们的 proto 层由 check_deps L2 禁止厂商 API。
