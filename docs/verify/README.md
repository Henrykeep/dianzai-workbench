# docs/verify —— 验证证据目录规范

“应该没问题”不算证据。每次验证（单测、仿真、台架、现场）都存一个目录，`requirements.yaml` 评分项的 `evidence` 指向它，
`tools/req.py evidence` 据此出合规与计分证据表（评分五元组 + 状态 + 禁止表述）。

## 结构
```
docs/verify/<题号>/                     例 docs/verify/2026H/
  logs/<YYYYMMDD-HHMM>_task<编号>_<层>/  例 logs/20261029-1940_taskB3_unit/
    notes.md         必有：谁测、场地、电源电压、现象、结论（tools/req.py newlog 自动建）
    flash.txt        台架/现场必有：烧录输出 + 固件版本（dzctl version 的 git hash）
    params.txt       台架/现场必有：参数全量回读（dzctl params 导出），与上次 last-good 可 diff
    run_NN.dzlog     工作台录像（每次一份）
    report/          tools/report.py 输出（results.md/csv、step.svg）
    test_output.txt  单元/仿真层：测试命令与完整输出
    video.txt        视频文件位置（视频本身太大不入库）
```
- **时间** 用 Asia/Shanghai，`YYYYMMDD-HHMM`；**编号** 用 requirements.yaml 的评分项编号（B3、A1）或 project.yaml 的 test_id；
- **层**：`unit` 单元测试、`sim` host-sim 仿真、`bench` 台架实物（不完全按题目测法）、`field` 现场（按题目测法、按次数完整走一遍）。
- **结果** `pass / fail / partial`。状态取最高一层的 pass：`现场通过 > 台架通过 > 仿真通过 > 单元通过`；只有 partial 时显示“X 部分”。
  **只有“现场通过”才能说已得分**——表里对其他状态自动加一条禁止表述“已得分”。

## 用法
```bash
python3 tools/req.py newlog --root docs/verify/2026H --task B3 --layer bench    # 建目录 + 打印 evidence 片段
# …测试、存 flash.txt / params.txt / 录像，跑 report.py（--req-file/--item 会把该项证据行带进报告）
python3 tools/req.py check    examples/2026H_ball/requirements.yaml              # 核对路径存在、目录名与 layer/date/编号一致、台架缺 flash/params 提醒
python3 tools/req.py evidence examples/2026H_ball/requirements.yaml -o out/      # 合规与计分证据表
```
目录名与 evidence 字段对不上（层、日期、编号）是错误；路径不存在是错误；空目录不算证据。

思路参考：DS-land-and-air 的合规差距清单与联调计分矩阵、MICU-auto-embedded 的评分点五元组（见 docs/参考来源.md）。
