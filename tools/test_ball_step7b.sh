#!/usr/bin/env bash
# 2026H_ball host-sim：真实 #38 阶跃路径（DATA 0x7B）。三个 pos_k（0.25/0.72/1.5，各自全新仿真）：
# ball_sp_px 写入被接收（协调器自动进 RUNNING）、0x7B 回 started、step_result 未中止、实验期间摆杆角非零且状态一直 RUNNING、三组指标明显不同。
# 回归 #67：2026H 没有 link.step（iterate_start → no_step_channel）、空闲不开环（角度恒 0、IDLE、钢珠漂）。make test 调用。
set -euo pipefail
cd "$(dirname "$0")/.."
a=2026H_ball; d=build/host-sim/$a
make -s BOARD=host-sim APP=$a >/dev/null
objs=$(find "$d/obj" -name '*.o' ! -name 'main_host.c.o')
cc -std=c11 -O1 -Wall -Werror -Ifirmware/common -Ifirmware/pal -Iports/host-sim -I$d/projgen -I$d/linkgen -Ibuild/host-sim/gen $(for x in firmware/*/* apps/include; do [ -d $x ] && echo -I$x; done) \
   -c tests/ballparam/ball_step7b.c -o "$d/ball_step7b.o"
cc "$d/ball_step7b.o" $objs -fsanitize=address,undefined -lm -o "$d/ball_step7b"
out=$(for k in 0.25 0.72 1.5; do "$d/ball_step7b" $k; done)
echo "$out" | sed 's/^/  /'
python3 - "$out" <<'PY'
import sys
rows = [dict(kv.split("=", 1) for kv in l.split() if "=" in kv) for l in sys.argv[1].strip().splitlines()]
bad = []
for r in rows:
    k = r["pos_k"]
    if "aborted" not in r: bad.append(f"pos_k={k} 没收到 step_result"); continue
    if r["ack"] != "0": bad.append(f"pos_k={k} PARAM_SET 被拒（{r['ack']}）")
    if r["sp_ok"] != "1": bad.append(f"pos_k={k} ball_sp_px 写入后协调器没进 RUNNING")
    if r["started"] != "0": bad.append(f"pos_k={k} 0x7B 回 {r['started']}，不是 started")
    if r["aborted"] != "0": bad.append(f"pos_k={k} 阶跃中止")
    if float(r["angle_max"]) < 0.1: bad.append(f"pos_k={k} 阶跃期间摆杆角恒 0")
    if r["run_all"] != "1": bad.append(f"pos_k={k} 阶跃期间状态不是 RUNNING")
    if abs(float(r["board_pos_k"]) - float(k)) > 1e-6: bad.append(f"pos_k={k} 板上 {r['board_pos_k']}")
m = [(float(r.get("ss", 0)), int(r.get("rise_ms", 0)), float(r.get("os", 0))) for r in rows]
for i in range(len(m)):
    for j in range(i + 1, len(m)):
        if abs(m[i][0] - m[j][0]) < 0.5 and abs(m[i][1] - m[j][1]) < 200 and abs(m[i][2] - m[j][2]) < 1.0:
            bad.append(f"pos_k {rows[i]['pos_k']} 与 {rows[j]['pos_k']} 的 step_result 几乎相同")
if bad:
    print("✗ [ball_step7b] " + "；".join(bad)); sys.exit(1)
print("✓ 2026H_ball：0x7B 阶跃路径可用，三组 step_result 各不相同，角度/状态正常")
PY
