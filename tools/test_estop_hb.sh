#!/usr/bin/env bash
# 每个带 LINK 的 host-sim 应用：ESTOP → 第一帧 bit10 心跳 ≤ 5 ms（10 个相位），带急停原因的心跳必须置 bit10；'R' 后锁存清且输出不自动恢复。make test 调用。
set -euo pipefail
cd "$(dirname "$0")/.."
APPS="${*:-car_2wd motor_pos pendulum_rot pan_tilt line_car 2026X_follow 2026H_ball}"
LIMIT_US=5000; fail=0
for a in $APPS; do
  make -s BOARD=host-sim APP=$a >/dev/null
  d=build/host-sim/$a; [ -d "$d" ] || d=$(ls -d build/*/$a | head -1)
  objs=$(find "$d/obj" -name '*.o' ! -name 'main_host.c.o')
  cc -std=c11 -O1 -Ifirmware/common -Ifirmware/pal -Iports/host-sim -Ibuild/host-sim/gen $(for x in firmware/*/* apps/include; do [ -d $x ] && echo -I$x; done) \
     -c tests/estop/estop_hb.c -o "$d/estop_hb.o"
  cc "$d/estop_hb.o" $objs -fsanitize=address,undefined -lm -o "$d/estop_hb"
  worst=0
  for k in 0 1 2 3 4 5 6 7 8 9; do
    read -r _ lat bad rb cl < <("$d/estop_hb" $k)
    if [ "$bad" != 0 ]; then echo "✗ [estop/hb] $a: 有 $bad 帧心跳带急停原因却没置 bit10"; fail=1; break; fi
    if [ "$cl" != 1 ]; then echo "✗ [estop/hb] $a 相位 $k: 'R' 后心跳仍带 bit10/急停原因"; fail=1; break; fi
    if [ "$rb" != 0 ]; then echo "✗ [estop/hb] $a 相位 $k: 'R' 后无新设定值输出却变了（自动恢复）"; fail=1; break; fi
    if [ "$lat" -lt 0 ] || [ "$lat" -gt $LIMIT_US ]; then echo "✗ [estop/hb] $a 相位 $k: ESTOP→bit10 心跳 ${lat} us > ${LIMIT_US} us"; fail=1; worst=$lat; break; fi
    [ "$lat" -gt "$worst" ] && worst=$lat
  done
  echo "  $a: 最坏 ${worst} us"
done
[ $fail = 0 ] && echo "✓ 急停心跳 ≤ 5 ms（$APPS）"
exit $fail
