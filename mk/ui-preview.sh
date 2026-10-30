#!/bin/sh
# make ui-preview：浏览器里预览桌面工作台（不用 Tauri）。
# 构建 app/ui（缺 node_modules 时 npm ci），在空闲端口 P 起侧车，侧车自带的静态服务在 P+1 提供 UI。
# Ctrl-C 结束。PY 可覆盖（默认 python3）。
set -e
PY=${PY:-python3}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT/app/ui"
[ -d node_modules ] || npm ci --no-audit --no-fund
npm run build --silent
P=$($PY -c '
import socket
for p in range(18765, 19765, 2):
    ok = True
    for q in (p, p + 1):
        s = socket.socket()
        try: s.bind(("127.0.0.1", q))
        except OSError: ok = False
        finally: s.close()
    if ok: print(p); break
')
[ -n "$P" ] || { echo "找不到空闲端口" >&2; exit 1; }
URL="http://127.0.0.1:$((P + 1))/?ws=ws://127.0.0.1:$P"
cd "$ROOT"
PYTHONPATH="$ROOT/app/sidecar" $PY -m dzbench --port "$P" --ui "$ROOT/app/ui/dist" &
PID=$!
trap 'kill $PID 2>/dev/null' INT TERM EXIT
# 等侧车静态服务起来再打印，保证地址是最后一块输出
for _ in $(seq 1 50); do
  $PY -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(('127.0.0.1', $((P + 1)))))" 2>/dev/null && break
  kill -0 $PID 2>/dev/null || { echo "侧车启动失败" >&2; exit 1; }
  sleep 0.2
done
sleep 0.3
printf '\n========================================================\n'
printf '  UI 预览（浏览器打开）：\n  %s\n' "$URL"
printf '  端口选“仿真板 · car_2wd”试用；Ctrl-C 结束\n'
printf '========================================================\n\n'
wait $PID
