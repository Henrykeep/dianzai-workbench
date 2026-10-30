# 净室规格：电压型 FOC（foc）、AS5600 磁编码器驱动（as5600）

- 状态：规格（只描述行为，不含实现代码）
- 基线：`origin/fw-runtime` @ `3cad235`（两个模块均为 2.0.0 桩实现，全部函数返回 `DZ_ENOTSUP` / 零输出）
- 规格作者：嵌入式开发-2（**不实现**）
- 实现者：后端开发者（未看过 `pid_helper`，实现期间也不得查看）
- 优先级：P1（与 biquad 一起重写，见 `README.md` 问题池）
- 目的：恢复 FOC 与 AS5600 功能，替换已移除的、参照过 GPL 代码的旧实现
- 版本：两个模块均升级到 **3.0.0**（主版本号变更，见第 4 节）

## 0. 来源记录（provenance）

### 0.1 编写本规格时读过的文件（仅公开接口）

| 文件（@`origin/fw-runtime`） | 用途 |
|---|---|
| `firmware/algo/foc/foc.h`（2.0.0 桩） | 保留公开 API 名称、签名、结构体字段名 |
| `firmware/drivers/as5600/as5600.h`（2.0.0 桩） | 同上 |

`git ls-tree` 列出过 `foc.c`、`as5600.c`、`README.md`、`tests/host/test_foc.c` 的路径名，**内容未打开**。

### 0.2 明确未打开的文件

`third_party/vendored/pid_helper` 全部文件及其 git 历史；`foc.c`、`as5600.c` 的任何版本（含桩）及其历史；`3cad235` 之前与这两个模块相关的任何提交的 diff；`tests/host/test_foc.c`。

### 0.3 结构说明

头文件中的结构体字段名保留（调用方可能直接读 `e->angle` 等，见内联函数），但**内部状态字段的含义和用法由实现者自行设计**（如 `phase/t/a0/a1/ol_angle/integ`）。如需增删内部字段，由实现者（后端开发者）实现完成后用工具重新生成 `iface.lock.json`（见第 4 节）。

### 0.4 公开参考文献（均非 GPL）

- [F1] Texas Instruments, *Field Orientated Control of 3-Phase AC-Motors*, Literature No. BPRA073, 1998（Clarke、Park、反 Park 变换、电流 / 速度环结构）
- [F2] Microchip, *AN1078: Sensorless Field Oriented Control of a PMSM*, 2010（坐标变换、PI 环与抗积分饱和、SVPWM 扇区）
- [F3] D. G. Holmes, T. A. Lipo, *Pulse Width Modulation for Power Converters*, Wiley-IEEE, 2003, ch. 3–6（SPWM、空间矢量调制、零序注入（min-max）与七段式 SVPWM 的等价性；线性调制区 |V| ≤ Vbus/√3）
- [F4] R. Krishnan, *Permanent Magnet Synchronous and Brushless DC Motor Drives*, CRC Press, 2010（电角度 = 极对数 × 机械角；转子初始位置对齐）
- [F5] K. J. Åström, T. Hägglund, *Advanced PID Control*, ISA, 2006, ch. 3（PI 抗积分饱和、条件积分 / 反算）
- [A1] ams OSRAM, *AS5600 Datasheet*, v1-06（I2C 7 位地址 0x36；寄存器 ZMCO 0x00、ZPOS 0x01–0x02、MPOS 0x03–0x04、MANG 0x05–0x06、CONF 0x07–0x08、RAW ANGLE 0x0C–0x0D、ANGLE 0x0E–0x0F、STATUS 0x0B（MH bit3、ML bit4、MD bit5）、AGC 0x1A、MAGNITUDE 0x1B–0x1C；12 位分辨率 0…4095；I2C 最高 1 MHz（Fast-mode Plus））。https://ams-osram.com/products/sensor-solutions/position-sensors/ams-as5600-position-sensor

## 1. 通用约定

- 角度单位为弧度（rad），角速度 rad/s，时间 s（`now_us` 为 µs），电压 V，占空比为 0…1 的无量纲数。
- 纯 C99，单精度 `float`，无动态内存，无阻塞等待，不依赖 libm 以外的库；可在 Cortex-M0+（无 FPU）上编译通过。
- 所有函数对 NULL 指针返回非 `DZ_OK` 错误码（`void` 函数直接返回，不写内存）。
- 任何输出（占空比、角度、速度）必须是有限值；输入出现 NaN/Inf 时按各节规定处理，不得把 NaN 传播到 PWM。
- **安全默认**：分两种情况（验收见 F-16）。
  - **(a) 急停或故障**（`FOC_FAULT`、上层急停锁存、参数非法导致的出错）：**优先关闭栅极驱动使能**（EN 拉低，桥臂输出高阻，电机自由滑行）。仅当硬件没有 EN 引脚（未提供驱动使能钩子）时，才退回三相占空比均为 0.5。退回方案的局限须知：0.5 占空比时线电压为零，但桥臂仍在开关、驱动芯片仍处于使能状态；电机若仍在转，反电动势会经桥臂形成制动电流（相当于短路刹车）。
  - **(b) 待机**（仅“状态不允许输出”，如未对齐时调用闭环函数、未启动）：三相 0.5 占空比可以保留，驱动使能状态保持不变。
  - 下文“零矢量输出”指三相 0.5；“安全停机”指情况 (a) 的行为。
- SPDX 许可证头与仓库一致；不得出现指向 `pid_helper` 的来源注释。

## 2. 组件一：电压型 FOC（`firmware/algo/foc`）

### 2.1 目的

无电流采样的电压型 FOC：输入机械角（多圈连续，通常来自 `as5600_angle_multi`），输出三相占空比 0…1。提供坐标变换、SVPWM、上电对齐、开环速度、角度单环、速度 PI 环、位置→速度串级。调用方按固定周期 dt 调用并自行写 PWM。

### 2.2 调用面（保持 2.0.0 签名不变）

| 函数 | 行为 |
|---|---|
| `void foc_clarke(float ia, float ib, float *alpha, float *beta)` | 幅值不变 Clarke [F1]：α = ia；β = (ia + 2·ib)/√3（隐含 ic = −ia − ib） |
| `void foc_park(float alpha, float beta, float th_e, float *d, float *q)` | d = α cosθ + β sinθ；q = −α sinθ + β cosθ |
| `void foc_ipark(float d, float q, float th_e, float *alpha, float *beta)` | α = d cosθ − q sinθ；β = d sinθ + q cosθ |
| `void foc_svpwm(float alpha, float beta, float vbus, float duty[3])` | 见 2.3 |
| `float foc_norm_angle(float a)` | 归一到 [0, 2π) |
| `dz_err_t foc_init(foc_t *f, const foc_cfg_t *cfg)` | 校验并拷贝 cfg、填默认值，state = `FOC_IDLE`，dir = +1，积分清零 |
| `float foc_elec_angle(const foc_t *f, float mech)` | `foc_norm_angle(dir · pole_pairs · mech − zero_e)` [F4] |
| `void foc_set_voltage(const foc_t *f, float uq, float ud, float th_e, float duty[3])` | 将 (ud, uq) 按 \|V\| ≤ v_limit 等比例限幅 → `foc_ipark` → `foc_svpwm(…, cfg.vbus, …)` |
| `dz_err_t foc_align_step(foc_t *f, float mech, float dt, float duty[3])` | 见 2.4；返回 `DZ_EBUSY` / `DZ_OK` / `DZ_EFAIL` |
| `dz_err_t foc_set_calibration(foc_t *f, float zero_e, int8_t dir)` | dir ∉ {+1, −1} 或 zero_e 非有限 → 错误；否则 zero_e 归一后保存，state = `FOC_READY` |
| `void foc_openloop_step(foc_t *f, float vel_mech, float uq, float dt, float duty[3])` | ol_angle += vel_mech · pole_pairs · dt（归一），`foc_set_voltage(f, uq, 0, ol_angle, duty)`；不需要对齐 |
| `dz_err_t foc_angle_step(…target, mech, vel, dt, duty)` | 单环 PID：e = target − mech；Uq = kp·e + ki·∫e − kd·vel（微分取测量速度，避免设定值突变冲击）；限幅 ±v_limit，抗饱和见 2.5 |
| `dz_err_t foc_velocity_step(…vel_target, mech, vel, dt, duty)` | 速度 PI：e = vel_target − vel；Uq = vel_kp·e + vel_ki·∫e，限幅 + 抗饱和 |
| `dz_err_t foc_pos_step(…target, mech, vel, dt, duty)` | 外环 P：vel_target = pos_kp·(target − mech)，限 ±vel_limit（0 = 不限），然后同 `foc_velocity_step` |
| `void foc_duty_to_pal(const float duty[3], uint16_t out[3])` | out = round(clamp(duty, 0, 1) · `PAL_DUTY_MAX`)；NaN → `PAL_DUTY_MAX/2` |
| `dz_err_t foc_selftest(void)` | 见 F-10 |

闭环函数（angle/velocity/pos）在 state ≠ `FOC_READY` 时返回 `DZ_EBUSY`（未对齐）或 `DZ_EFAIL`（FAULT），并输出零矢量。所有闭环中电角度用 `foc_elec_angle(f, mech)`，Ud = 0。

`foc_init` 默认值：v_limit ≤ 0 或 > vbus/√3 → 取 vbus/√3；v_align = 0 → v_limit/2；t_align_s = 0 → 0.5 s。

**驱动使能钩子（向后兼容新增）**：现有函数签名一律不变。`foc_cfg_t` 末尾新增可选字段 `void (*driver_enable)(void *ctx, bool on)` 与 `void *driver_ctx`；新增函数 `void foc_safe_stop(foc_t *f, float duty[3])`（急停/故障入口）。规则：
- `driver_enable == NULL`（旧代码零初始化 cfg 时即为此值）→ 视为无 EN 引脚，`foc_safe_stop` 输出零矢量。
- 非 NULL → `foc_safe_stop` 调用 `driver_enable(ctx, false)`，duty 仍写 0.5（作为高阻失效时的兜底），此后在 `foc_set_calibration` 或显式重新使能前不得再调用 `driver_enable(ctx, true)`；进入 `FOC_FAULT` 时内部自动调用 `foc_safe_stop`。
- 待机路径（情况 b）不调用 `driver_enable`。
- `foc_init` 调用 `driver_enable(ctx, false)`；`foc_align_step` 开始输出前调用 `driver_enable(ctx, true)`。
- 板级接线由板子的 pal 层把 EN 引脚包装成该回调；没有 EN 的板子不填。

### 2.3 SVPWM 算法 [F3]

采用 min-max 零序注入（与七段式中心对齐 SVPWM 等价）：

1. 反 Clarke：va = α；vb = −α/2 + (√3/2)β；vc = −α/2 − (√3/2)β。
2. 过调制处理：若 \|(α, β)\| > vbus/√3，按比例缩到 vbus/√3（保持方向）。
3. voff = (max(va,vb,vc) + min(va,vb,vc))/2；dutyₓ = 0.5 + (vₓ − voff)/vbus。
4. 最终 clamp 到 [0, 1]（数值保险）。

vbus ≤ 0 或非有限、或 α/β 非有限 → 零矢量输出。

### 2.4 上电对齐 [F4]

`foc_align_step` 是非阻塞状态机，每次调用推进 dt：

1. **段 A（锁零点）**：在电角度 θ = 0 施加 Ud = v_align（Uq = 0）t_align_s 秒；结束时记 a0 = mech。
2. **段 B（转一个电周期的分数）**：以 Ud = v_align、电角度从 0 线性扫到 +2π（用时 t_align_s）；结束时记 a1 = mech。
3. **判定**：Δ = a1 − a0。
   - \|Δ\| < 0.1 · (2π / pole_pairs) → 转子未动：`FOC_FAULT`，返回 `DZ_EFAIL`（典型原因：未上电、相线断、v_align 过小）。
   - dir = sign(Δ)；pp_est = 2π / \|Δ\|。若 \|pp_est − pole_pairs\| > 0.5 → `FOC_FAULT`，`DZ_EFAIL`，pp_est 保留供上层提示“极对数不符，估计为 N”。
4. 回到 θ = 0 再锁 t_align_s 后，zero_e = `foc_norm_angle(dir·pole_pairs·mech)`，state = `FOC_READY`，返回 `DZ_OK`。

对齐期间返回 `DZ_EBUSY`；`FOC_FAULT` 后再次调用保持零矢量并返回 `DZ_EFAIL`，直到 `foc_init` 重新初始化。

### 2.5 抗积分饱和 [F5]

条件积分：若本周期未限幅输出已饱和、且误差与输出同号，则积分不累加；否则 ∫e += e·dt。积分项本身亦限制在 ±v_limit 对应范围内。切换模式（如由 velocity 切到 angle）不要求无扰，但积分不得携带 NaN。

### 2.6 边界情况与报错

| 情况 | 行为 |
|---|---|
| `pole_pairs == 0` | `foc_init` 返回错误（`DZ_EINVAL` 或仓库等价码），state = `FOC_FAULT` |
| `pole_pairs > 50` | 视为无效（同上）。合法范围 1…50 |
| vbus ≤ 0 / 非有限；kp 等增益为负或非有限 | `foc_init` 错误 |
| dt ≤ 0 或非有限 | 本步不更新状态，零矢量输出，闭环返回错误 |
| mech、vel、target 非有限 | 零矢量输出，不更新积分，返回错误 |
| 角度归一：a = ±1e6 rad、a = −0.0、a = 2π | `foc_norm_angle` 结果在 [0, 2π)，2π 映射为 0 |
| 输出饱和 | \|(Ud,Uq)\| 按比例限到 v_limit；SVPWM 再限六边形内切圆；占空比恒在 [0,1] |
| 多圈角度大值 | 角度误差 e 直接用多圈值相减（不 wrap），以支持多圈定位 |

### 2.7 验收测试（容差为单精度）

| 编号 | 场景 | 期望 |
|---|---|---|
| F-1 | Clarke：ia=1, ib=−0.5（ic=−0.5） | α = 1 ± 1e-6，β = 0 ± 1e-6；ia=0, ib=1 → β = 2/√3 ± 1e-6 |
| F-2 | Park/反 Park 往返：α, β ∈ [−10, 10]，θ 在 [−4π, 4π] 随机 10⁴ 组（固定种子） | 往返误差 ≤ 1e-5·max(1,\|v\|)；且 d²+q² = α²+β²（相对误差 ≤ 1e-5） |
| F-3 | Clarke→Park 对平衡正弦三相 i = I·cos(θ − k·2π/3)，θ 扫一圈 | d = I ± 1e-4·I，q = 0 ± 1e-4·I |
| F-4 | SVPWM 占空比边界：\|V\| 从 0 到 2·vbus 扫，角度扫一圈（vbus=12） | 所有 duty ∈ [0, 1]；V=0 时三相 = 0.5 ± 1e-6 |
| F-5 | SVPWM 线性区：\|V\| = 0.9·vbus/√3 | 由 duty 反算线电压 (dₐ−d_b)·vbus 等与输入的线电压误差 ≤ 1e-4·vbus；三相平均值偏离 0.5 ≤ 1e-6 |
| F-6 | 过调制：\|V\| = 2·vbus/√3 | 输出与 \|V\| = vbus/√3 同方向的结果一致（≤ 1e-5）；max(duty)−min(duty) ≤ 1 |
| F-7 | 电角度：pole_pairs=7, dir=+1, zero_e=0, mech=2π/7 | `foc_elec_angle` = 0 ± 1e-5（≡ 2π）；mech=π/7 → π ± 1e-5；dir=−1 时为 2π − 原值 |
| F-8 | 对齐（宿主机仿真电机：转子在 Ud 下按一阶跟随电角度，pp=7，传感器方向 −1，零偏 1.234 rad） | 返回 `DZ_OK`，dir=−1，pp_est = 7 ± 0.3，此后 `foc_elec_angle` 与仿真真值误差 ≤ 0.05 rad |
| F-9 | 对齐失败：仿真转子不动；或 pp 配置 7 实际 11 | 前者 `DZ_EFAIL`、state=FAULT；后者 `DZ_EFAIL`、pp_est = 11 ± 0.5；两者占空比均为零矢量 |
| F-10 | `foc_selftest()` | 内部跑 F-1、F-2（100 组）、F-4（固定 24 点）、F-7，全部通过返回 `DZ_OK` |
| F-11 | pole_pairs=0、vbus=0、dt=0、mech=NaN | 分别按 2.6 返回错误，duty 三相 = 0.5 |
| F-12 | 闭环（同 F-8 仿真电机，叠加 J、B）：`foc_velocity_step` 目标 10 rad/s | 1 s 内进入 ±5% 并保持；Uq 恒 ≤ v_limit；目标阶跃到不可达值 1000 rad/s 后再回 10 rad/s，0.5 s 内回到 ±5%（验证抗饱和） |
| F-13 | `foc_pos_step` 目标 +4π（两圈） | 终值误差 ≤ 0.02 rad，超调 ≤ 10%，\|vel_target\| ≤ vel_limit |
| F-14 | 开环：pp=7, vel_mech=2π rad/s, dt=1e-3, 1000 步 | ol_angle 累计电角度 = 14π（mod 2π）± 1e-3 |
| F-15 | `foc_duty_to_pal` | {0, 0.5, 1, −0.1, 1.2, NaN} → {0, 5000, 10000, 0, 10000, 5000} |
| F-16 | 安全默认两种行为：(1) 带 EN 的仿真驱动（回调记录 EN 电平，桥臂开关计数），运行中触发 `foc_safe_stop` 及 FAULT；(2) 同场景 `driver_enable = NULL`；(3) 未对齐时调用 `foc_velocity_step`（待机） | (1) EN 被拉低，此后开关计数不再增加，且直到重新校准前不会被重新拉高；(2) duty 三相 = 0.5 ± 1e-6；(3) duty 三相 = 0.5，EN 回调未被调用（电平不变）。实板测试记入使用者的实机测试清单 |

## 3. 组件二：AS5600 驱动（`firmware/drivers/as5600`）

### 3.1 目的

经 PAL I2C 读取 AS5600 的 12 位原始角，在软件中完成零点、方向、多圈展开、速度估计和磁铁状态检查。**不写 OTP**（不烧 ZPOS/MPOS/MANG，不发 BURN 命令）。

### 3.2 寄存器（[A1]，只读子集）

| 寄存器 | 地址 | 用途 |
|---|---|---|
| STATUS | 0x0B | bit5 MD = 检测到磁铁；bit4 ML = 磁场太弱；bit3 MH = 磁场太强 |
| RAW ANGLE | 0x0C (高 4 位), 0x0D (低 8 位) | 12 位 0…4095，不受 ZPOS/MPOS/MANG 影响。**驱动只用此寄存器** |
| ANGLE | 0x0E, 0x0F | 经 ZPOS/MPOS 缩放后的角度，驱动不使用（文档说明区别） |
| AGC | 0x1A | 自动增益（供诊断） |
| MAGNITUDE | 0x1B (高 4 位), 0x1C | CORDIC 幅值（供诊断） |

raw = ((b0 & 0x0F) << 8) | b1；一次 2 字节连续读。1 LSB = 2π/4096 rad ≈ 0.0879°。

### 3.3 调用面（保持 2.0.0 签名不变）

| 函数 | 行为 |
|---|---|
| `dz_err_t as5600_init(as5600_t *e, const as5600_cfg_t *cfg)` | 校验 cfg（dir ∈ {+1,−1}，vel_tau_s ≥ 0 且有限），清零状态，读一次 STATUS 探测器件（I2C 不应答 → 返回 I2C 错误码，`has=false`） |
| `dz_err_t as5600_check_magnet(as5600_t *e, uint8_t *status)` | 读 STATUS，`*status`（可为 NULL）与 `e->status` 均写原值。MD=0 → `DZ_ENODEV`；MD=1 且 (ML 或 MH) → `DZ_EFAIL`；MD=1 且二者为 0 → `DZ_OK` |
| `dz_err_t as5600_update(as5600_t *e, uint32_t now_us)` | 读 RAW ANGLE，更新 raw/angle/turns/angle_multi/vel/t_us，见 3.4 |
| `dz_err_t as5600_set_zero_here(as5600_t *e)` | 读一次 raw 作为 zero，turns=0，angle=angle_multi=0，速度滤波器清零 |
| `as5600_angle / _angle_multi / _velocity` | 内联读取字段（不变） |
| `dz_err_t as5600_selftest(void)` | 纯软件自检（不访问 I2C），见 A-10 |

### 3.4 角度、多圈与速度

- 单圈：c = (dir · (raw − zero)) mod 4096（结果 0…4095）；angle = c · 2π/4096。
- 多圈展开：Δc = c − c_prev，若 Δc > 2048 则 Δc −= 4096，若 Δc < −2048 则 Δc += 4096（最短路径，要求两次 update 之间转动 < 半圈，即 |ω| < π/Δt）；累计 count += Δc，turns = floor(count/4096)，angle_multi = count · 2π/4096。累计计数用 int32/int64 保存，避免 float 长时间累加误差。
- 速度：Δt = (uint32_t)(now_us − t_us)（无符号差，天然处理 `pal_micros` 32 位回绕）；v_raw = Δc·2π/4096 / Δt。一阶低通：α = Δt/(τ + Δt)，vel += α(v_raw − vel)；τ = 0 时 vel = v_raw。
- 首次成功 update：只建立基准（has=true），vel = 0，ready 在第二次成功 update 后置 true。
- Δt = 0：角度照常更新，速度不更新。Δt > 0.5 s（长时间未调用）：重新建立速度基准（vel 置 0 并标记），多圈仍按最短路径展开。

### 3.5 边界情况与报错

| 情况 | 行为 |
|---|---|
| I2C 读失败（NACK / 超时） | 返回 PAL 错误码，`errors++`，**所有角度 / 速度字段保持上一次值**，不更新 t_us |
| 连续 I2C 失败 ≥ 10 次 | ready = false（上层据此停 FOC），恢复后需重新建立基准（vel=0） |
| 读回 raw 高 4 位非 0（总线噪声） | 视为 I2C 错误，同上 |
| 磁铁缺失（MD=0）| `as5600_check_magnet` 返回 `DZ_ENODEV`；`as5600_update` 不检查 STATUS（避免每周期多一次 I2C），由上层定期调用 check_magnet |
| 回绕 4095↔0 | 按 3.4 最短路径，不产生 ±2π 跳变 |
| now_us 回绕（2³²µs ≈ 71.6 min） | 无符号差，速度无跳变 |
| NULL 指针 / 未 init | 返回错误，不访问 I2C |

### 3.6 验收测试（宿主机用 PAL I2C 假实现注入 raw 序列与错误）

| 编号 | 场景 | 期望 |
|---|---|---|
| A-1 | raw 解析：字节 (0x0F, 0xFF) / (0x00, 0x00) / (0x08, 0x00) | 4095 / 0 / 2048；angle = 2π·4095/4096 ± 1e-6 等 |
| A-2 | 正向跨零：raw 4090→4095→0→5 | angle_multi 单调增，总增量 = 11·2π/4096 ± 1e-6，turns 由 0 变 1 |
| A-3 | 反向跨零：raw 5→0→4095→4090 | 总增量 = −11·2π/4096 ± 1e-6，turns 由 0 变 −1 |
| A-4 | dir = −1：A-2 的序列 | angle_multi 总增量 = −11·2π/4096 ± 1e-6 |
| A-5 | 零点：zero=1000 后 raw=1000 | angle = 0；raw=999 → angle = 2π·4095/4096 ± 1e-6 |
| A-6 | 合成匀速斜坡：ω = 10 rad/s，Δt = 1 ms，raw = round(ω t·4096/2π) mod 4096，2 s，τ = 0.005 | 0.05 s 后 \|vel − 10\| ≤ 0.1 rad/s（≈ 量化噪声经 τ 滤波）；angle_multi 终值 = 20 ± 2π/4096·2 rad |
| A-7 | 反向斜坡 ω = −50 rad/s；以及跨 now_us 回绕（t 从 0xFFFFF000 起） | 同 A-6 容差（相对 1%），回绕处无速度尖峰（\|vel − ω\| ≤ 1%·\|ω\|） |
| A-8 | 半圈边界：每步 2047 计数 / 2049 计数 | 前者按正向展开；后者被识别为反向 2047（文档化的已知限制） |
| A-9 | 磁铁：STATUS = 0x20 / 0x00 / 0x30 / 0x28 | `DZ_OK` / `DZ_ENODEV` / `DZ_EFAIL` / `DZ_EFAIL`，`*status` 为原值 |
| A-10 | `as5600_selftest()` | 纯软件跑 A-1、A-2、A-3、A-6（缩短为 0.2 s）的计算部分，通过返回 `DZ_OK` |
| A-11 | I2C 注入错误 1 次 / 连续 10 次后恢复 | 1 次：返回错误，字段不变，errors=1；10 次：ready=false，恢复后首个成功 update vel=0，第二次后 ready=true |
| A-12 | 与 FOC 联调（宿主机）：A-6 的 as5600 输出喂给 F-12 | 速度环同样满足 F-12 指标 |

## 4. 版本与接口锁

1. `FOC_VERSION`、`AS5600_VERSION` 及各自 `VERSION` 文件改为 **3.0.0**（主版本：2.0.0 是“停用桩”，3.0.0 为全新净室实现，行为与 1.x 不保证一致，例如错误码与零矢量安全输出）。
2. **iface.lock 重新生成**：实现者不要手改 `iface.lock.json`；实现完成后由实现者（后端开发者）运行仓库的接口锁生成命令（`make` 中锁生成目标）重新生成 `firmware/algo/foc` 与 `firmware/drivers/as5600` 两个条目，并在提交说明中写明“主版本 3.0.0，接口锁重建”。既有函数原型与 2.0.0 一致；预期变化为新增 `foc_safe_stop`、`foc_cfg_t` 末尾的驱动使能钩子字段、结构体内部字段（若实现者调整）和版本号。
3. 模块 README 写明：净室实现、参考文献 [F1]–[F5]、[A1]，删除“已停用”说明。

## 5. 整体验收

1. `make check` rc=0（含 `licenses`），`make test` 0 失败 **0 跳过**，`make cross` 全部目标通过且无新警告（含 M0+ 无 FPU 目标）。
2. F-1…F-16、A-1…A-12 均有自动化宿主测试（`tests/host/`）并通过。现有 `tests/host/test_foc.c` 由实现者**按本规格重写**（实现者与规格作者都不打开旧文件内容；直接以新文件覆盖）。
3. 引用 foc / as5600 的应用（如电机 FOC 类题目的 app）在 sim 下 `make test` 通过；实机验证由使用者按 F-8、F-12、A-9 在 AS5600 + 云台电机上复测。
4. 新文件头 SPDX 标识与仓库一致，无指向 `pid_helper` 的来源注释。
5. 实现者在 PR 说明中声明：实现期间未查看 0.2 所列文件，只参考了本规格和 0.4 文献。
