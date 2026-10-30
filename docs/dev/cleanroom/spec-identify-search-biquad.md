# 净室规格：对象辨识（identify）、PID 增益选择（search）、二阶 IIR 滤波器（biquad）

- 状态：规格（只描述行为，不含实现代码）
- 基线：`origin/fw-runtime` @ `420311f`
- 规格作者：嵌入式开发-2（**不实现**）
- 实现者：后端开发者（未看过 `pid_helper`、ArduPilot 源码，实现期间也不得查看）
- 目的：替换提交 `5d03e24`、`7916e17` 中的实现，解除 GPL 污染风险

## 0. 来源记录（provenance）

### 0.1 编写本规格时读过的文件（仅调用方，用于确定调用面）

| 文件（@420311f） | 用途 |
|---|---|
| `app/sidecar/tests/test_identify.py` | identify 的调用方式、返回字段、错误类型、稳态判定原因码 |
| `app/sidecar/tests/test_search.py` | search 的调用方式、返回结构、可复现性和实机门禁 |
| `app/sidecar/tests/test_relay.py` | 继电自整定模块与 search 仿真器的交互（`relay` 模块本身不在本次重写范围） |
| `app/sidecar/dzbench/agent/service.py`（第 26、612–628、895–915 行附近） | `steady_state`、`search_from_step` 的调用与错误转换 |
| `app/sidecar/dzbench/agent/experiment.py`、`app/sidecar/dzbench/agent/bench.py`（仅文件头和 import） | 确认调用关系、`GuardError` 来源 |
| `tests/host/test_lpf.c`（第 40–70 行） | biquad 的 C 调用方式和现有相位滞后测试 |
| `iface.lock.json`（`firmware/algo/lpf` 条目） | 被锁定的 C 函数原型 |
| `Makefile`（grep "bench"） | 基准入口 |

另外 `git grep` 的输出中出现过 `firmware/algo/lpf/README.md` 第 10 行（一行函数用途说明），未打开该文件。

### 0.2 明确未打开的文件

以下内容在编写本规格时**均未打开、未 grep 内容、未查看 git 历史**：
已删除的 `pid_helper` 全部文件及其历史；ArduPilot 源码及 `refs/ext/ardupilot`；旧 `biquad.c` 与 lpf 的历史版本；`5d03e24`、`7916e17` 中的 `app/sidecar/dzbench/tuning/identify.py`、`app/sidecar/dzbench/tuning/search.py`、`firmware/algo/lpf/biquad.c`、`firmware/algo/lpf/biquad.h`。
（只用 `git ls-tree` 列出过这些文件的路径名。）

### 0.3 结构说明

`iface.lock.json` 锁定了 `biquad.h` 里结构体的字段列表。本规格**不规定**结构体内部布局，只规定函数原型与行为；实现者自行设计内部状态，随后由统筹者决定是否更新 `iface.lock.json`（这属于接口锁的更新，不是行为变化）。

### 0.4 公开参考文献

- [R1] S. Skogestad, "Simple analytic rules for model reduction and PID controller tuning," *Journal of Process Control*, vol. 13, no. 4, pp. 291–309, 2003. doi:10.1016/S0959-1524(02)00062-8
- [R2] K. J. Åström, T. Hägglund, "Automatic tuning of simple regulators with specifications on phase and amplitude margins," *Automatica*, vol. 20, no. 5, pp. 645–651, 1984. doi:10.1016/0005-1098(84)90014-1
- [R3] K. J. Åström, T. Hägglund, *Advanced PID Control*, ISA, 2006. ISBN 978-1-55617-942-6（第 2、6、7 章：模型、整定规则、继电反馈）
- [R4] C. L. Smith, *Digital Computer Process Control*, Intext Educational Publishers, 1972（两点法 28.3 % / 63.2 % 辨识 FOPDT）
- [R5] D. E. Seborg, T. F. Edgar, D. A. Mellichamp, F. J. Doyle III, *Process Dynamics and Control*, 4th ed., Wiley, 2016. ISBN 978-1-119-28591-5（第 7 章 经验模型辨识）
- [R6] R. Bristow-Johnson, "Cookbook formulae for audio EQ biquad filter coefficients"（Audio EQ Cookbook），W3C 公开版：https://www.w3.org/TR/audio-eq-cookbook/
- [R7] J. Kennedy, R. Eberhart, "Particle swarm optimization," *Proc. IEEE ICNN*, 1995, pp. 1942–1948. doi:10.1109/ICNN.1995.488968
- [R8] Y. Shi, R. Eberhart, "A modified particle swarm optimizer," *Proc. IEEE ICEC*, 1998, pp. 69–73. doi:10.1109/ICEC.1998.699146（惯性权重）
- [R9] A. V. Oppenheim, R. W. Schafer, *Discrete-Time Signal Processing*, 3rd ed., Pearson, 2010（直接 II 型转置结构、量化与稳定性）
- [R10] K. J. Åström, R. M. Murray, *Feedback Systems*, 2nd ed., Princeton Univ. Press, 2021（积分抗饱和、性能指标）

允许使用的第三方库（许可证已由资料/仓库搜索者核对）：`numpy`、`scipy`（BSD-3）、`python-control`（BSD-3）。不得引入任何 GPL/AGPL 或无许可证代码；`make check` 的 `licenses` 目标会拦截。

---

## 1. 通用约定

- 时间单位一律为秒（s），频率为 Hz，角度为弧度（除非字段名带 `_deg`）。
- 被控量 y、控制量 u 的单位由调用方决定，本模块不假设量纲；**不得使用绝对幅值阈值**（例如“变化至少 0.2”），所有阈值相对于信号自身的幅度或噪声水平（见现有测试：K = −0.02 的小量纲反向对象必须能辨识）。
- 输入序列为等长的 Python 序列（list/tuple/ndarray），采样可以略不均匀；实现可内部重采样到中位采样间隔。
- 所有面向用户的错误信息为中文，说明“原因 + 下一步该做什么”。
- 函数为纯函数：不读写文件、不访问网络、不依赖全局随机状态；需要随机数时由参数给种子。
- 返回字典中的浮点数必须是有限值（`math.isfinite`），不能出现 NaN/Inf。

## 2. 组件一：对象辨识（identify）

### 2.1 目的

从开环阶跃数据中辨识一阶惯性加纯滞后模型（FOPDT），可选二阶（SOPDT），据此给出 SIMC 初始 PID；并判定一段响应是否已到稳态。

模型：
- FOPDT：G(s) = K·e^(−θs) / (τs + 1)
- SOPDT：G(s) = K·e^(−θs) / ((τ₁s + 1)(τ₂s + 1))，τ₁ ≥ τ₂ ≥ 0

### 2.2 调用面（中性名 → 现有调用方要求的绑定名）

模块路径 `dzbench.tuning.identify`（被调用方 import，路径不变）。

| 中性描述 | 必须提供的绑定名 |
|---|---|
| 辨识失败异常（`Exception` 子类，消息为中文原因） | `IdentError` |
| 开环阶跃 → 模型 + SIMC 增益 | `open_loop_pid(t, y, t_step, du, u=None)` |
| 稳态判定 | `steady_state(t, y, t_step=None, window_s=..., span_ref=None)` |

#### `open_loop_pid`

输入：
| 参数 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `t` | 序列[float] | s | 单调不减 |
| `y` | 序列[float] | y 单位 | 被控量 |
| `t_step` | float | s | 阶跃时刻（第 3 个位置参数） |
| `du` | float | u 单位 | 阶跃幅度，非零（第 4 个位置参数） |
| `u` | 序列[float] 或 None | u 单位 | 若给出，用于核对/修正实际阶跃时刻与幅度 |

输出 dict（至少包含）：
| 键 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `K` | float | y/u | 稳态增益，可为负 |
| `tau_s` | float | s | 时间常数 τ（SOPDT 时为 τ₁） |
| `dead_s` | float | s | 纯滞后 θ，≥ 0 |
| `pid` | dict `{p, i, d}` | — | 并联形式 u = p·e + i·∫e dt + d·de/dt；`i` > 0，`d` ≥ 0；K < 0 时增益符号按对象符号给出（与现有测试一致：K<0 时 p 的符号随 1/K） |
| `model` | str | — | `"fopdt"` 或 `"sopdt"` |
| `fit_rmse` | float | y 单位 | 模型阶跃响应与数据的均方根误差 |
| `tau_c_s` | float | s | 使用的 SIMC 闭环时间常数 |

#### `steady_state`

输入：`t`、`y` 同上；`t_step`（float 或 None，None 表示按全序列判定）；`window_s`（判定窗口长度，默认值由实现者取，建议 0.3 s）；`span_ref`（参考幅度，通常是设定值跳变量；None 时用数据自身幅度）。

输出 dict：`steady`（bool）、`reason`（str，取值见下）、`text`（中文说明）。

| `reason` | 含义 | `steady` |
|---|---|---|
| `steady` | 尾窗内无显著趋势、无显著振荡 | True |
| `too_few_samples` | 样本数不足以判定（建议门限：少于 10 点或尾窗少于 5 点） | False |
| `warming_up` | 阶跃后经过的时间还不足一个判定窗口 | False |
| `too_little_motion` | 阶跃前后变化相对 `span_ref` 太小（无响应） | False |
| `oscillating` | 尾窗内过零/峰谷次数和幅度表明持续振荡 | False |
| `still_drifting` | 尾窗内线性趋势外推到窗口长度后仍占 `span_ref` 的显著比例 | False |

判定顺序：`too_few_samples` → `warming_up` → `too_little_motion` → `oscillating` → `still_drifting` → `steady`。阈值相对 `span_ref`，具体数值由实现者选，必须通过 2.6 中的测试。

### 2.3 算法（按公开文献）

1. **预处理**：取 t_step 之前的样本均值为 y₀；取末尾若干比例（建议最后 20 %，至少 5 点）的均值为 y∞。Δy = y∞ − y₀；K = Δy / du [R5 §7]。
2. **噪声与有效性**：用阶跃前样本的标准差 σ₀（无阶跃前样本时用尾段去趋势后的标准差）估计噪声。若 |Δy| < max(5σ₀, 机器精度量级的相对门限) → `IdentError("阶跃后被控量几乎没变化 …")`。
3. **两点法初值** [R4][R5]：归一化响应 r(t) = (y − y₀)/Δy，求 r 首次达到 0.283 和 0.632 的时刻 t₁、t₂（线性插值），τ = 1.5(t₂ − t₁)，θ = t₂ − τ − t_step，θ < 0 时取 0。
4. **最小二乘精修**（推荐）：以两点法为初值，用 `scipy.optimize.least_squares` 在 (K, τ, θ) 上最小化模型阶跃响应与数据的残差，约束 τ > 0、θ ≥ 0。FOPDT 阶跃响应：y(t) = y₀ + K·du·(1 − e^(−(t−t_step−θ)/τ))，t > t_step+θ，否则 y₀。
5. **SOPDT（可选）**：同样以最小二乘拟合 (K, τ₁, τ₂, θ)；仅当 RMSE 比 FOPDT 小 20 % 以上时采用，否则报告 FOPDT。
6. **SIMC 整定** [R1]：
   - FOPDT：τc = max(θ, τ/2)（若调用方没有给出更快/更慢的选择）；Kc = τ / (K(τc + θ))；τI = min(τ, 4(τc + θ))；τD = 0。
   - SOPDT：Kc = τ₁ / (K(τc + θ))；τI = min(τ₁, 4(τc + θ))；τD = τ₂（串联形式）。
   - 串联 → 并联换算：p = Kc(1 + τD/τI)，i = Kc/τI，d = Kc·τD [R1 §4]。
   - 若 θ 估计为 0，τc 取 max(τ/2, 2·采样间隔)，避免增益无穷大。

### 2.4 边界情况与报错

| 情况 | 行为 |
|---|---|
| 长度不一致、少于 10 点、t 非单调 | `IdentError`（中文，说明需要的数据） |
| du = 0 或 u 序列中找不到跳变 | `IdentError` |
| 无响应（见 2.3-2） | `IdentError` |
| 阶跃后数据不足以到达 63.2 %（未稳） | `IdentError("响应还没稳定，请加长录制时间 …")` |
| 含 NaN/Inf 的样本 | 丢弃该点；丢弃超过 10 % 时 `IdentError` |
| 反向对象（K<0） | 正常辨识，K 为负 |
| 拟合不收敛 | 回退到两点法结果，并在输出里加 `"fit": "two_point"` |

`IdentError` 会被 `service.py` 转为 `search_failed` 错误码，所以消息必须是可直接展示给用户的中文。

### 2.5 精度要求

在无噪声 FOPDT 合成数据（采样间隔 ≤ τ/20）上：K 相对误差 ≤ 3 %，τ 相对误差 ≤ 15 %，θ 绝对误差 ≤ max(0.04 s, 2 个采样间隔)。在噪声幅度为 |Δy| 的 1 % 时：K ≤ 5 %，τ ≤ 20 %。

### 2.6 验收测试（参考对象与期望范围）

| 编号 | 对象 / 数据 | 期望 |
|---|---|---|
| I-1 | FOPDT K=2, τ=0.5 s, θ=0.1 s, du=1, t_step=0.5 s, dt=0.01 s, 4 s | K∈[1.94, 2.06]；τ∈[0.425, 0.575]；θ∈[0.06, 0.14]；SIMC p∈(0.6, 0.85)，i>0，d≥0（理论 τc=0.25，Kc≈0.714） |
| I-2 | FOPDT K=−0.02, τ=0.3, θ=0.05 | K∈[−0.021, −0.019] |
| I-3 | K=0，仅含 0.01 幅度扰动 | 抛出 `IdentError` |
| I-4 | FOPDT K=1, τ=1, θ=0.2，加 1 % 白噪声（固定种子） | K 误差 ≤ 5 %，τ ≤ 20 %，θ 绝对误差 ≤ 0.05 |
| I-5 | SOPDT K=1, τ₁=1, τ₂=0.3, θ=0.1 | 选择 sopdt 时 τ₁∈[0.85,1.15]，τ₂∈[0.2,0.4]；或报告 fopdt 且 θ+τ 合计 ∈[1.2,1.6]（Skogestad 半规则近似） |
| I-6 | `steady_state` 的 6 种原因码 | 与现有 `test_steady_reasons` 场景一致：稳定 FOPDT → steady；τ=5 s 窗口内 → still_drifting；5 点 → too_few_samples；正弦尾 → oscillating；平线 → too_little_motion；仅 60 点 → warming_up |

## 3. 组件二：PID 增益选择（search）

### 3.1 目的

给定一个评估函数（通常是 FOPDT 闭环仿真），从初始增益出发搜索更好的 PID 增益；提供 FOPDT 闭环仿真器、统一评分函数，以及“开环阶跃数据 → 辨识 → 搜索”的一站式入口。只在仿真中跑全局搜索；实机上禁止粒子群（会生成未经护栏的大量候选）。

继电自整定（Åström–Hägglund [R2]）由现有 `dzbench.tuning.relay` 提供，不在本次重写范围；但 search 的仿真器必须能闭合其输出的增益（见 S-7）。

### 3.2 调用面

模块路径 `dzbench.tuning.search`。

| 中性描述 | 必须提供的绑定名 |
|---|---|
| FOPDT 闭环仿真 → 指标 | `simulate_fopdt(gains, K, T, L, t_end=..., u_lim=...)` |
| 指标 → 标量分数（相对基线，越小越好） | `score(metrics, baseline_metrics)` |
| 搜索 | `optimize(evaluate, seed, strategy=..., sim=..., iterations=..., swarm=..., rng_seed=..., bounds=None, wide=False, top_k=3)` |
| 阶跃数据 → 辨识 → 搜索 | `search_from_step(t, y, u, seed=None, strategy=..., iterations=..., wide=False, top_k=3)` |

`GuardError` 从 `dzbench.agent.experiment` 引入，不重新定义。

#### `simulate_fopdt`

- `gains`：dict `{kp, ki, kd}`（并联形式）；`K`（y/u）、`T`（s）、`L`（s）可位置或关键字传入；`t_end`（s，默认建议 3.0）；`u_lim`（控制量限幅，默认建议 1.0 量级，由实现者定并写入文档字符串）。
- 仿真：单位设定值阶跃 r=1；离散步长 dt ≤ min(T, L)/10 且 ≤ 5 ms；纯滞后用延迟队列；对象用精确离散化 x[k+1] = a·x[k] + K(1−a)·u[k−n]，a = e^(−dt/T)；PID 微分作用于测量值并带一阶滤波（N = 10，[R3 §3]）；输出限幅加条件积分抗饱和 [R10]。
- 输出 dict（全部有限值，发散时截断到大的有限值）：`itae`、`iae`、`overshoot`（比例，0.1 = 10 %）、`settling_s`（2 % 带）、`rise_s`（10–90 %）、`steady_error`（末尾 10 % 的平均绝对误差，相对设定值）、`control_ripple`（末尾段 u 的标准差相对 u_lim）。

#### `score`

标量，越小越好；基线自身得分 = 1.0。建议形式：加权的 itae/itae_base + 超调、稳态误差、控制量纹波的惩罚项。不稳定或发散的增益必须得到 > 1.0 的分数或使 `control_ripple` > 0.05，且不能抛异常。

#### `optimize`

- `evaluate(gains) -> metrics`：调用方提供。
- `seed`：初始增益 dict `{kp, ki, kd}`。
- `strategy`：`"pso"`（粒子群 [R7][R8]）或 `"staged"`（分阶段坐标搜索：先 kp，再 ki，再 kd，每阶段做一维有界搜索，可用 `scipy.optimize.minimize_scalar`）。
- `sim`：bool。`strategy == "pso"` 且 `sim` 为 False 时，**在任何评估之前**抛出 `GuardError`（中文原因：粒子群只允许在仿真中运行）。
- `bounds`：dict `{name: (lo, hi)}`；缺省时以种子为中心取范围（普通模式建议 [0, 4×seed+小正数]，`wide=True` 时放宽到至少 10 倍）。所有候选必须落在边界内。
- `rng_seed`：用 `random.Random(rng_seed)` 或 `numpy.random.default_rng(rng_seed)`；相同参数两次调用结果必须完全相同。
- 输出 dict：`baseline`（`{gains, metrics, score}`，score=1.0）；`best`（同结构）；`top`（长度 `top_k` 的列表，按 score 升序，互不重复）；`wide`（bool）；`strategy`；`evaluations`（评估次数）。
- PSO 参数参考 [R8]：惯性权重从 0.9 线性降到 0.4，c₁ = c₂ ≈ 2.0，速度限幅为边界宽度的 20 %。种子作为一个粒子加入初始群。

#### `search_from_step`

1. 用组件一的 `open_loop_pid` 辨识（t_step 和 du 从 u 序列的最大跳变自动得到）。
2. 种子：调用方提供的 `seed` 中有非零增益则用之，否则用 SIMC 增益。
3. 以 `simulate_fopdt(·, K, τ, θ)` 为评估函数调用 `optimize(..., sim=True)`。
4. 输出：`optimize` 的结果 + `model`：`{K, tau_s, dead_s, seed_from}`，`seed_from ∈ {"identify", "user"}`（未提供有效种子时为 `"identify"`）。
- u 序列无跳变 → `ValueError`（中文）；辨识失败 → 透传 `IdentError`。

### 3.3 边界情况与报错

| 情况 | 行为 |
|---|---|
| 实机（sim=False）+ pso | `GuardError`，不做任何评估 |
| evaluate 抛异常或返回非有限值 | 该候选记为极差分数，继续；全部失败时 `ValueError` |
| bounds 中 lo > hi | `ValueError` |
| iterations ≤ 0 或 swarm < 2 | `ValueError` |
| 增益使仿真发散 | 不抛异常，指标截断为有限大值 |

### 3.4 精度与性能

- 同一 `rng_seed` 结果逐位相同（跨进程）。
- `simulate_fopdt` 在 t_end=3 s 下单次 ≤ 20 ms（参考机），`optimize(iterations=12, swarm=8)` ≤ 5 s。
- 在 T=1, L=0.2, K=2 上，SIMC 增益的仿真超调 ≤ 15 %，稳态误差 ≤ 2 %。

### 3.5 验收测试

| 编号 | 场景 | 期望 |
|---|---|---|
| S-1 | 对象 K=2, T=0.3, L=0.05；种子 kp=0.3, ki=0.1, kd=0；pso 与 staged 各跑 iterations=12, swarm=8, rng_seed=1 | best.score < 0.95；best.itae < baseline.itae；top 长 3 且升序 |
| S-2 | 同参数调用两次（pso, rng_seed=7） | best 完全相同；sim=False 时 `GuardError` |
| S-3 | 增益 kp=ki=50 | 指标全部有限；score > 1.0 或 control_ripple > 0.05 |
| S-4 | bounds kp∈[0,0.5], ki∈[0,0.3], kd∈[0,0.01] | top 中所有候选在边界内 |
| S-5 | 开环 FOPDT K=2, T=0.3, L=0.05, du=0.5, dt=5 ms 的阶跃数据 → `search_from_step(staged, iterations=8)` | |model.K − 2| < 0.3；seed_from == "identify"；best.score ≤ 1.0；top 长 3 |
| S-6 | wide=True vs 普通（pso, 同种子） | wide 的 best.score ≤ 普通 + 1e-9；staged+wide best.score < 0.8 |
| S-7 | `relay.relay_sim(2,1,0.2)` 给出的增益在 `simulate_fopdt(..., u_lim=10)` 下 | steady_error < 0.05，overshoot < 0.8；TL 规则超调小于 ZN 规则 |

## 4. 组件三：二阶 IIR 滤波器（biquad，C 固件）

### 4.1 目的

供固件控制环使用的二阶低通（Butterworth，Q = 1/√2）和陷波滤波器，单精度浮点，无动态内存，可在 Cortex-M4F/M0+ 上运行。

### 4.2 调用面（由 `iface.lock.json` 与 `tests/host/test_lpf.c` 固定）

头文件 `firmware/algo/lpf/biquad.h`，类型名 `biquad_t`（内部字段由实现者设计，见 0.3），错误类型 `dz_err_t`（`DZ_OK` 表示成功）。

| 函数 | 行为 |
|---|---|
| `dz_err_t lpf2p_init(biquad_t *f, float cutoff_hz, float sample_hz)` | 按 [R6] LPF 公式、Q=1/√2 计算系数；清状态 |
| `dz_err_t notch_init(biquad_t *f, float center_hz, float bw_hz, float att_db, float sample_hz)` | 陷波：中心 f₀、带宽 bw_hz（−3 dB 带宽，Hz）、中心处衰减 att_db（正数，dB） |
| `float biquad_update(biquad_t *f, float x)` | 输入一个样本，返回滤波输出 |
| `void biquad_reset(biquad_t *f, float x0)` | 把内部状态设为输入恒为 x0 时的稳态（输出立即为 DC 增益·x0） |
| `void biquad_clear(biquad_t *f)` | 状态清零，下一次 update 时以首个有效样本自动 reset（“首样本预置”） |
| `dz_err_t biquad_selftest(void)` | 内置自检，见 4.6 B-6 |

### 4.3 算法 [R6]

记 w₀ = 2π f₀ / Fs，α = sin(w₀)/(2Q)。

- 低通（LPF）：
  b₀ = (1 − cos w₀)/2，b₁ = 1 − cos w₀，b₂ = (1 − cos w₀)/2，
  a₀ = 1 + α，a₁ = −2 cos w₀，a₂ = 1 − α；Q = 1/√2。
- 陷波（notch）基本形式：
  b₀ = 1，b₁ = −2 cos w₀，b₂ = 1，a₀ = 1 + α，a₁ = −2 cos w₀，a₂ = 1 − α。
  带宽到 α 的换算按 [R6] 带宽形式：α = sin(w₀)·sinh( (ln2/2)·BW_oct·w₀/sin(w₀) )，其中 BW_oct = log₂((f₀ + bw/2)/(f₀ − bw/2))。
  **有限衰减**：理想陷波在 f₀ 处为 −∞ dB。为得到中心衰减 A = att_db，用 [R6] 的 peakingEQ 公式，增益 dBgain = −att_db：A_lin = 10^(dBgain/40)，
  b₀ = 1 + α·A_lin，b₁ = −2 cos w₀，b₂ = 1 − α·A_lin，a₀ = 1 + α/A_lin，a₁ = −2 cos w₀，a₂ = 1 − α/A_lin。
  att_db ≤ 0 或 ≥ 120 时视为“无限深”，使用基本陷波形式。
- 全部系数除以 a₀ 归一化。
- 差分方程采用直接 II 型转置结构 [R9 §6.4]（对单精度系数量化更稳健）：
  y = b₀x + s₁；s₁ = b₁x − a₁y + s₂；s₂ = b₂x − a₂y。
- 系数计算在 init 中用 double 或 float 均可，存储为 float。

### 4.4 边界情况与报错

| 情况 | 行为 |
|---|---|
| `f == NULL` | 返回非 DZ_OK 错误码，不写内存 |
| `sample_hz ≤ 0`、非有限 | 错误 |
| `cutoff_hz ≤ 0` 或 `≥ 0.5·sample_hz`（奈奎斯特）或非有限 | 错误，滤波器置为直通（输出 = 输入）以免未初始化使用 |
| notch：`center_hz` 不在 (0, Fs/2)、`bw_hz ≤ 0`、`center_hz − bw_hz/2 ≤ 0` 或 `center_hz + bw_hz/2 ≥ Fs/2` | 错误，置直通 |
| update 输入 NaN/Inf | 丢弃该样本，返回上一次输出，状态不变 |
| 内部状态变为非有限 | 下一次有效输入时自动 reset 到该输入 |
| 未 primed 时首个有效样本 | 自动 `biquad_reset(f, x)`，避免启动时从 0 爬升 |

### 4.5 精度要求

- 频率响应：在 0.001·Fs … 0.45·Fs 之间对数取 200 点，实现的 |H(e^{jω})| 与按 [R6] 公式用 double 计算的理论值比较：通带与过渡带（|H| > −40 dB）误差 ≤ 0.1 dB；阻带（|H| ≤ −40 dB）误差 ≤ 1 dB；相位误差 ≤ 0.5°（|H| > −20 dB 处）。
- LPF：DC 增益 1 ± 1e-5；f = fc 处 −3.01 ± 0.1 dB。
- 陷波：DC 与 0.45·Fs 处增益 1 ± 0.01（0 ± 0.1 dB）；f₀ 处衰减 att_db ± 0.5 dB（有限深形式）或 ≤ −40 dB（无限深形式）。
- 稳定性：所有合法参数下极点模 < 1；fc 低至 Fs/1000 时单精度仍稳定，阶跃响应最终值误差 ≤ 1e-3。
- 实时性：`biquad_update` 无分支循环、无除法，Cortex-M4F 上 ≤ 30 周期（参考）。

### 4.6 验收测试

| 编号 | 场景 | 期望 |
|---|---|---|
| B-1 | 现有 `lpf2p_less_lag_than_lpf1`：fs=1 kHz，fc=32.7 Hz，2 Hz 正弦过零滞后 | 4.9° ± 0.6°（与 lpf1 fc=9.9 Hz 的 11.1° 对比） |
| B-2 | LPF fs=1 kHz, fc ∈ {1, 10, 50, 200, 400} Hz 的频响扫描 | 满足 4.5 容差 |
| B-3 | 陷波 fs=1 kHz, f₀=100 Hz, bw=20 Hz, att=40 dB | f₀ 处 −40 ± 0.5 dB；50 Hz 与 200 Hz 处 |H| ≥ −1 dB |
| B-4 | 非法参数（见 4.4 每一行） | 返回错误，滤波器直通 |
| B-5 | NaN 输入、首样本预置、reset(x0) 后立即输出 x0 | 分别符合 4.4 |
| B-6 | `biquad_selftest()` | 内部用固定参数（如 fs=1 kHz、fc=50 Hz）验证 DC 增益、fc 处 −3 dB、陷波中心衰减三项，全部在 4.5 容差内返回 `DZ_OK` |
| B-7 | `make cross` | 所有目标编译通过，无警告 |

## 5. 整体验收

1. `make check` rc=0（含 `licenses` 目标），`make test` 0 失败 **0 跳过**，`make cross` 全过。
2. 上述 I-1…I-6、S-1…S-7、B-1…B-7 全部有对应自动化测试并通过；现有 `test_identify.py`、`test_search.py`、`test_relay.py`、`tests/host/test_lpf.c` 不改断言即通过。
3. **基准**：使用与 `420311f` 记录 85.9 分时相同的基准（同一对象、种子和重复次数，4 个案例 motor_pos、2026H、2013C、2023E），**总平均 ≥ 85.9**；逐案例不得下降超过 1.0 分，任何案例不得由通过变为未通过。报告前后分数表。
4. 新文件头加 SPDX 许可证标识（与仓库一致），不得出现指向 `pid_helper`、ArduPilot 的来源注释。
5. 实现者在 PR 说明中声明：实现期间未查看 0.2 所列文件，只参考了本规格和 0.4 文献。
