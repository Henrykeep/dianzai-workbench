#!/usr/bin/env bash
# 急停 → 'R' 后设定值归零（r7 motor_pos 解除后 sp 停在 90°）：每个带 LINK 设定值的 host-sim 应用跑 60 个相位/场景，
# 锁存中和 'R' 后 1 s 遥测设定值 == 0、u == 0，'R' 后不动。make test 调用。
set -euo pipefail
cd "$(dirname "$0")/.."
APPS="${*:-motor_pos pendulum_rot pan_tilt line_car car_2wd}"
N=${ESTOP_SP_N:-60}; fail=0
for a in $APPS; do
  make -s BOARD=host-sim APP=$a >/dev/null
  d=build/host-sim/$a
  objs=$(find "$d/obj" -name '*.o' ! -name 'main_host.c.o')
  read -r types flags < <(python3 - "$d/linkgen/link_gen.c" <<'PY'
import re,sys
s=open(sys.argv[1]).read().split("link_telem_pack",1)[1]
s=s[s.index("return"):s.index("\n}")]
ty={"u32":"I","u16":"H","u8":"B","f32":"f"}; T="";F=""
for t,n in re.findall(r"put_(u32|u16|u8|f32)\(f, (?:\(\w+\))?t->(\w+)\)",s)[1:]:
    T+=ty[t]; F+="s" if t=="f32" and re.match(r"(sp_|.*_sp_|aim_)",n) else "u" if n=="u" else "-"
assert T and "s" in F, "遥测里没找到设定值字段"
print(T,F)
PY
)
  case $a in car_2wd) V=0.3;; *) V=30;; esac
  cc -std=c11 -O1 -Ifirmware/common -Ifirmware/pal -Iports/host-sim -Ibuild/host-sim/gen -I"$d/linkgen" $(for x in firmware/*/* apps/include; do [ -d $x ] && echo -I$x; done) \
     -c tests/estop/estop_sp.c -o "$d/estop_sp.o"
  cc "$d/estop_sp.o" $objs -fsanitize=address,undefined -lm -o "$d/estop_sp"
  bad=0; lw=0; lsum=0
  for k in $(seq 0 $((N-1))); do
    read -r _ lb cb ub pb nt lz < <("$d/estop_sp" $k "$types" "$flags" $V)
    if [ "$lz" -lt 0 ]; then echo "✗ [estop/sp] $a 相位 $k: 锁存后 sp 一直没归零"; fail=1; bad=$((bad+1)); continue; fi
    [ "$lz" -gt "$lw" ] && lw=$lz; lsum=$((lsum+lz))
    if [ "$nt" -lt 50 ]; then echo "✗ [estop/sp] $a 相位 $k: 遥测太少（$nt 帧）"; fail=1; bad=$((bad+1)); continue; fi
    if [ "$lb" != 0 ] || [ "$cb" != 0 ] || [ "$ub" != 0 ] || [ "$pb" != 0 ]; then
      echo "✗ [estop/sp] $a 相位 $k 场景 $((k%4)): 锁存中 sp≠0 ${lb} 帧，'R' 后 sp≠0 ${cb} 帧，u≠0 ${ub} 帧，PWM 变 ${pb} 次"; fail=1; bad=$((bad+1)); fi
  done
  echo "  $a: $N 次，失败 $bad；ESTOP→遥测 sp=0 平均 $((lsum/N)) us、最坏 ${lw} us（字段 $types / $flags）"
done
[ $fail = 0 ] && echo "✓ 急停/'R' 设定值归零、不自动恢复（$APPS）"
exit $fail
