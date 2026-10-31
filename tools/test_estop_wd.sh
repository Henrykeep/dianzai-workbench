#!/usr/bin/env bash
# 每个带 LINK 的 host-sim 应用：上位机卡顿 1.2 s 不许急停；卡顿 2 s 必须急停，原因 = 心跳超时(2)，记录值 = 实测间隔（与测试量的差 ≤ 5 ms，且 ≥ 阈值）。make test 调用。
set -euo pipefail
cd "$(dirname "$0")/.."
APPS="${*:-car_2wd motor_pos pendulum_rot pan_tilt line_car}"
fail=0
for a in $APPS; do
  make -s BOARD=host-sim APP=$a >/dev/null
  d=build/host-sim/$a
  objs=$(find "$d/obj" -name '*.o' ! -name 'main_host.c.o')
  inc=$(for x in firmware/*/* apps/include; do [ -d $x ] && echo -I$x; done)
  cc -std=c11 -O1 -Ifirmware/common -Ifirmware/pal -Iports/host-sim -Ibuild/host-sim/gen -I"$d/gen" -I"$d/link_gen" $inc $(find "$d" -name link_gen.h -printf '-I%h ') \
     -c tests/estop/estop_wd.c -o "$d/estop_wd.o"
  cc "$d/estop_wd.o" $objs -fsanitize=address,undefined -lm -o "$d/estop_wd"
  { read -r _ c1 _ _; read -r _ thr; } < <("$d/estop_wd" 1200)
  { read -r _ c2 v2 g2; } < <("$d/estop_wd" 2000)
  if [ "$c1" != 0 ]; then echo "✗ [estop/wd] $a: 主机卡顿 1.2 s 误触发急停（原因 $c1，阈值 $thr ms）"; fail=1; continue; fi
  if [ "$c2" != 2 ]; then echo "✗ [estop/wd] $a: 主机卡顿 2 s 没有心跳超时急停（原因 $c2，阈值 $thr ms）"; fail=1; continue; fi
  if [ "$v2" -lt "$thr" ] || [ $((v2 - g2)) -gt 5 ] || [ $((g2 - v2)) -gt 5 ]; then
    echo "✗ [estop/wd] $a: 急停记录值 ${v2} ms 不是实测间隔 ${g2} ms（阈值 $thr ms）"; fail=1; continue; fi
  echo "  $a: 阈值 ${thr} ms；1.2 s 卡顿不触发；2 s 卡顿触发，记录 ${v2} ms / 实测 ${g2} ms"
done
[ $fail = 0 ] && echo "✓ 链路看门狗：卡顿 1.2 s 不误触发、2 s 必触发且记录实测间隔（$APPS）"
exit $fail
