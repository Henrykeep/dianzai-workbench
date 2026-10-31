#!/usr/bin/env python3
"""子系统模板生成器：在题目目录下生成一个新子系统的骨架 + 用模拟数据的单元测试。

  python3 tools/new_subsys.py examples/<例题> gimbal --owns gimbal_out --reads vision_out --period 5

生成：
  <题目>/subsys/<name>/<name>.c      实现 init/step/on_mode/selftest，只读写共享状态
  <题目>/subsys/<name>/README.md     职责、输入（reads）、输出（owns）、参数、如何单独测试
  <题目>/subsys/<name>/VERSION       0.1.0（入库前达到 1.0.0，见 docs/04-入库检查清单.md）
  <题目>/tests/test_<name>.c         模拟数据单测骨架
然后手动把它加进 project.yaml 的 subsystems（脚本会打印要粘贴的片段）。不覆盖已存在的文件。
"""
import argparse
import pathlib
import sys

C_TMPL = '''/**
 * 子系统 {name}：TODO 一句话职责。
 * 读：{reads}    写（唯一写者）：{owns}
 * 规则：不包含其他子系统、不碰硬件（pal/驱动），只读写共享状态 —— 这样可以用模拟数据单独测试。
 */
#include "project_gen.h"

static dz_err_t {name}_init(void *state, const void *params)
{{
    shared_state_t *st = state; (void)params;
    (void)st;  /* TODO 初始化自己 owns 的段 */
    return DZ_OK;
}}

static void {name}_step(void *state, const void *params, uint32_t now_ms)
{{
    shared_state_t *st = state; const params_t *p = params;
    (void)st; (void)p; (void)now_ms;
    /* TODO 从 reads 段取输入，计算，只写 owns 段 */
}}

static void {name}_on_mode(void *state, subsys_mode_t mode)
{{
    shared_state_t *st = state;
    (void)st;
    if (mode != SUBSYS_MODE_RUN) {{ /* TODO 输出安全值 */ }}
}}

static dz_err_t {name}_selftest(void) {{ return DZ_OK; /* TODO 用固定输入检查输出 */ }}

const subsys_t SUBSYS_{NAME} = {{ "{name}", PERIOD_MS_{NAME}, false, {name}_init, {name}_step, {name}_on_mode, {name}_selftest }};
'''

T_TMPL = '''/* 子系统 {name} 的模拟数据测试：直接构造共享状态，不需要任何硬件或其他子系统。 */
#include "tt.h"
#include "project_gen.h"

TEST({name}_basic)
{{
    shared_state_t st = {{0}};
    const params_t *p = &g_project_params[0];
    CHECK(SUBSYS_{NAME}.init(&st, p) == DZ_OK);
    /* TODO：写入 reads 段的模拟输入 -> step -> 检查 owns 段 */
    SUBSYS_{NAME}.step(&st, p, 0);
    CHECK(SUBSYS_{NAME}.selftest() == DZ_OK);
}}

void suite_{name}(void) {{ RUN({name}_basic); }}
'''

R_TMPL = '''# 子系统 {name}

- 职责：TODO
- 周期：{period} ms
- 读（reads）：{reads}
- 写（owns，唯一写者）：{owns}
- 用到的参数（params_t）：TODO
- 单独测试：`make -C <题目目录>/tests`，测试只构造共享状态，不需要硬件
- 版本：见 VERSION；入库规则见 docs/04-入库检查清单.md
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=pathlib.Path)
    ap.add_argument("name")
    ap.add_argument("--owns", nargs="*", default=[])
    ap.add_argument("--reads", nargs="*", default=[])
    ap.add_argument("--period", type=int, default=10)
    a = ap.parse_args()
    n = a.name
    if not n.isidentifier() or n.lower() != n or n in ("io", "coord"):
        print("子系统名须为小写标识符，且不能是 io/coord", file=sys.stderr)
        return 1
    d = a.project_dir / "subsys" / n
    files = {
        d / f"{n}.c": C_TMPL,
        d / "README.md": R_TMPL,
        d / "VERSION": "0.1.0\n",
        a.project_dir / "tests" / f"test_{n}.c": T_TMPL,
    }
    kw = dict(name=n, NAME=n.upper(), owns=", ".join(a.owns) or "（无）", reads=", ".join(a.reads) or "（无）", period=a.period)
    for path, tmpl in files.items():
        if path.exists():
            print(f"跳过（已存在）{path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tmpl.format(**kw), encoding="utf-8")
        print(f"生成 {path}")
    print("\n请把下面片段加入 project.yaml：")
    print(f"  subsystems:\n    - {{ name: {n}, board: main, period_ms: {a.period}, owns: {a.owns}, reads: {a.reads} }}")
    for s in a.owns:
        print(f"  state:\n    {s}: {{ owner: {n}, fields: [ ... ] }}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
