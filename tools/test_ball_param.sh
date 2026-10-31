#!/usr/bin/env bash
# 2026H_ball host-sim：上位机 PARAM_SET 写的 pos_k 必须真的进钢珠环。三个 pos_k（各自全新仿真，第 1 轮）阶跃指标要明显不同，
# 且 'T'1 选中的是小题 id 1（base 档）。回归：'T' 曾把 n 当下标，选中小题 2（fast 档），写的参数全不生效、三组指标一模一样。make test 调用。
set -euo pipefail
cd "$(dirname "$0")/.."
a=2026H_ball; d=build/host-sim/$a
make -s BOARD=host-sim APP=$a >/dev/null
objs=$(find "$d/obj" -name '*.o' ! -name 'main_host.c.o')
cc -std=c11 -O1 -Wall -Werror -Ifirmware/common -Ifirmware/pal -Iports/host-sim -I$d/projgen -I$d/linkgen -Ibuild/host-sim/gen $(for x in firmware/*/* apps/include; do [ -d $x ] && echo -I$x; done) \
   -c tests/ballparam/ball_step.c -o "$d/ball_step.o"
cc "$d/ball_step.o" $objs -fsanitize=address,undefined -lm -o "$d/ball_step"
out=$(for k in 0.25 1.5 0.1; do "$d/ball_step" 1.0 4.0 $k; done)
echo "$out" | sed 's/^/  /'
python3 - "$out" <<'PY'
import sys
rows = [l.split() for l in sys.argv[1].strip().splitlines()]
bad = []
for r in rows:
    if r[2] != "1": bad.append(f"pos_k={r[1]} 没收到 PARAM_ACK")
    if abs(float(r[9]) - float(r[1])) > 1e-6: bad.append(f"pos_k={r[1]} 板上当前档 pos_k={r[9]}")
    if r[-1] != "test_id=1": bad.append(f"'T'1 选中的是 {r[-1]}，不是小题 1")
ss = [float(r[8]) for r in rows]; xs = [float(r[4]) for r in rows]
for i in range(3):
    for j in range(i + 1, 3):
        if abs(ss[i] - ss[j]) < 2.0 and abs(xs[i] - xs[j]) < 2.0:
            bad.append(f"pos_k {rows[i][1]} 与 {rows[j][1]} 的阶跃指标几乎相同（ss_err {ss[i]} / {ss[j]}，x_at_step {xs[i]} / {xs[j]}）：参数没进钢珠环")
if bad:
    print("✗ [ball_param] " + "；".join(bad)); sys.exit(1)
print("✓ 2026H_ball：PARAM_SET 的 pos_k 实时生效，三组阶跃指标各不相同")
PY
