#!/usr/bin/env bash
# 一条命令装好并挂上芯台全部 MCP 服务：tools/mcp/up.sh [--http 端口]
#   1. .venv-mcp（继承系统包）装 mcp<2、pyvisa、platformio 等；
#   2. 编 embedded-debugger-mcp（cargo）和 sigrok-mcp-server（go）到 build/mcp/；
#   3. 写 build/mcp/mcp.json（绝对路径，任何支持 MCP 的助手直接挂）；
#   4. 逐个 initialize + tools/list 冒烟，打印每个服务的工具数或失败原因；
#   5. 给了 --http：前台起芯台服务的 streamable HTTP（http://127.0.0.1:端口/mcp）。
# 不碰密钥；某一步失败只报不停。
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
V=$ROOT/third_party/vendored
OUT=$ROOT/build/mcp
VENV=${XINTAI_MCP_VENV:-$ROOT/.venv-mcp}
mkdir -p "$OUT"
[ -x "$VENV/bin/python" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install -q 'mcp>=1.20,<2' 'pyvisa>=1.14' 'pyvisa-py>=0.7' 'pydantic>=2.6' pyserial pyyaml uvicorn starlette platformio \
  || echo "✗ pip 安装没全部成功（离线？），继续用已有的包"
if command -v cargo >/dev/null; then
  (cd "$V/embedded_debugger_mcp" && CARGO_TARGET_DIR="$OUT/edm-target" cargo build -q --release --locked) \
    && cp "$OUT/edm-target/release/embedded-debugger-mcp" "$OUT/" || echo "✗ embedded-debugger-mcp 编译失败（Linux 要 libudev-dev、pkg-config）"
else echo "✗ 没有 cargo，跳过 embedded-debugger-mcp"; fi
if command -v go >/dev/null; then
  (cd "$V/sigrok_mcp_server" && go build -o "$OUT/sigrok-mcp-server" ./cmd/sigrok-mcp-server) || echo "✗ sigrok-mcp-server 编译失败"
else echo "✗ 没有 go，跳过 sigrok-mcp-server"; fi
PY=$VENV/bin/python
"$PY" "$ROOT/tools/mcp/mkconfig.py" --root "$ROOT" --python "$PY" --bin "$OUT" -o "$OUT/mcp.json"
"$PY" "$ROOT/tools/mcp/smoke.py" "$OUT/mcp.json"
echo "MCP 配置：$OUT/mcp.json"
if [ "${1:-}" = "--http" ]; then
  cd "$ROOT/app/sidecar" && exec "$PY" -m dzbench.mcp_server --http "${2:-8765}"
fi
