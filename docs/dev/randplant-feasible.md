# randplant 可行性标签与复核 API（#124 / #125）

负责人：嵌入式开发-2。判卷侧（`tools/tunegate.py`）归后端，这里只给接口。

## plant.json / `randplant.gen(seed)` 的字段

| 字段 | 取值 | 含义 |
|---|---|---|
| `feasible` | `true` / `false` / `"unknown"` | `true`：找到一组满足题面全部条目的参数；`false`：可证明做不到（饱和），或细搜最好违约比 > `UNSURE`（1.5）；`"unknown"`：细搜最好违约比在 (1, 1.5]，不敢下结论 |
| `reason_category` | `saturation` / `delay_too_large` / `unstable_zero` / `steady_state_error` / `spec_too_tight` / `null` | 按模型结构判（`randplant.classify`），不再沿用注入标签；`true` 时为 `null` |
| `feasibility.method` | `coarse_grid` / `refine` | 标签出自粗网格还是细搜 |
| `feasibility.violation` | 数 / `null` | 细搜最好一组的 max(实测/题面)，≤1 即达标 |
| `feasibility.witness` | `{参数名: 值}` / `null` | `true` 时一定有：满足题面的一组参数（按 app.yaml 里的参数名），可直接在仿真上复算 |

注意：`"unknown"` 在 Python 里是真值，判卷请用 `feasible is True` / `is False` / `== "unknown"` 区分，不要 `bool()`。
`tools/tunegate_plant.py` 现在是 `bool(rp["feasible"])`，`"unknown"` 会被当成可行——请后端改成透传。

指标口径与 `dzbench.tuning.autotune.metrics` 一致（`randplant.judge_metrics`）：尾段 15% 均值误差、对目标超调、±5% 带调节时间；
仿真时长 `max(horizon_s, 900·dt)`，模型就是固件同一个（饱和、死区、Padé 滞后、传感器限幅、采样周期、LIM 参数）。

## `tools/feascheck.py`

```python
import feascheck, randplant
p = randplant.gen(seed)
feascheck.recheck(p)                  # 独立细搜（换种子、4 倍预算）→ {"feasible", "violation", "witness"}
feascheck.judge(p, verdict, met)      # verdict: 卡上结论；met: 判卷在真值上复算是否满足题面
                                      # → "ok" | "false_pass" | "undecided"
feascheck.summarize({seed: feasible}) # → {"n", "unknown", "ratio", "unknown_seeds"}
```

建议 tunegate 的用法：
- 卡上 pass 且真值不满足 → 假达标（不管标签）。
- 卡上 pass、标签 `false` → `recheck`；复核 `true` 说明标签错、卡片对，不算假达标。
- 标签 `"unknown"`：卡上 pass 且真值满足 → 通过；否则 `recheck`，仍 `"unknown"` 则 `judge` 返回 `undecided`：**单独计数，不进通过率分母**。

CLI：`python3 tools/feascheck.py --seeds "3001-3012 4001-4040" --max-unknown 0.10`
打印 true/false/unknown 个数和 unknown 比例，比例超过阈值（默认 10%，也可用环境变量 `FEAS_MAX_UNKNOWN`）退出码 2（警告级）。
`tests/randplant/test_feasible.py`（make test）守着：独立搜索达标 ⇒ 不许 `false`；原因类别对结构分类器；unknown 比例 ≤ 阈值。
