# 净室重写（clean-room）

规格作者只写行为规格，实现者只按规格与公开文献实现，双方均不得查看 GPL 来源（`pid_helper` 及其历史）。

| 规格 | 模块 | 目标版本 | 优先级 | 负责人 | 状态 |
|---|---|---|---|---|---|
| [spec-identify-search-biquad.md](spec-identify-search-biquad.md) | identify、search、biquad | biquad 主版本 +1 | P1 | 后端开发者 | 待实现 |
| [spec-foc-as5600.md](spec-foc-as5600.md) | `firmware/algo/foc`、`firmware/drivers/as5600` | 3.0.0 | P1 | 后端开发者 | 待实现 |

## 问题池条目

问题池在仓库外的共享目录 `/workspace/charter/问题池.md`，由使用者维护；CR-1、CR-2 由后端开发者登记在该处。以下为条目摘要，以问题池为准。

- **CR-1（P1，后端开发者）**：biquad / identify / search 净室重写，按 `spec-identify-search-biquad.md`，验收见其第 5 节；实现完成后由实现者（后端开发者）用工具重新生成 iface.lock（biquad 主版本 +1）。
- **CR-2（P1，后端开发者）**：foc + as5600 净室重写（当前为 2.0.0 停用桩，影响电机 FOC 类题目），与 CR-1 一起排期，验收见 `spec-foc-as5600.md` 第 5 节；实现完成后由实现者（后端开发者）用工具重新生成 iface.lock。
