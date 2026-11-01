#!/usr/bin/env bash
# fetch_third_party.sh 下载重试 + sha256（CI run 41199129663：m0pack curl exit 56）。
# 用 PATH 里的假 curl：前两次 exit 56，第三次写出正确内容 → 必须成功且确实重试；
# 内容永远不对 → 必须失败、且不留下 .pack / .tmp。
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
mkdir -p "$w/bin" "$w/repo/tools"
cp "$root/tools/fetch_third_party.sh" "$root/tools/fetch_lib.sh" "$w/repo/tools/"
cat > "$w/bin/curl" <<'C'
#!/usr/bin/env bash
if [ "${1:-}" = --help ]; then echo "--retry-all-errors"; exit 0; fi
n=$(( $(cat "$CNT" 2>/dev/null || echo 0) + 1 )); echo $n > "$CNT"; echo "$*" >> "$CNT.args"
out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
[ "$n" -le "${FAILS:-0}" ] && exit 56
printf '%s' "$BODY" > "$out"
C
chmod +x "$w/bin/curl"
good=$(printf 'pack-ok' | sha256sum | cut -d' ' -f1)
sed -i "s/^M0PACK_SHA=[0-9a-f]*/M0PACK_SHA=$good/" "$w/repo/tools/fetch_third_party.sh"
f="$w/repo/third_party/packs/TexasInstruments.MSPM0G1X0X_G3X0X_DFP.1.3.1.pack"
run() { PATH="$w/bin:$PATH" FETCH_SLEEP=0 CNT="$w/cnt" bash "$w/repo/tools/fetch_third_party.sh" m0pack; }
# 1) 瞬断两次后成功
rm -f "$w/cnt"*; FAILS=2 BODY=pack-ok run >/dev/null
[ "$(cat "$w/cnt")" = 3 ] || { echo "✗ 应重试到第 3 次，实际 $(cat "$w/cnt")"; exit 1; }
[ "$(cat "$f")" = pack-ok ] || { echo "✗ 包内容不对"; exit 1; }
grep -q -- '--retry-all-errors' "$w/cnt.args" && grep -q -- '--retry 5' "$w/cnt.args" || { echo "✗ curl 没带 --retry/--retry-all-errors"; exit 1; }
echo "✓ exit 56 两次后重试成功（3 次 curl）"
# 2) sha 永远不符 → 失败，不留坏文件
rm -f "$f" "$w/cnt"*
if FAILS=0 BODY=tampered FETCH_TRIES=3 run >/dev/null 2>&1; then echo "✗ sha 不符竟然成功"; exit 1; fi
[ ! -e "$f" ] && [ ! -e "$f.tmp" ] || { echo "✗ 留下了坏文件"; exit 1; }
[ "$(cat "$w/cnt")" = 3 ] || { echo "✗ sha 不符应重试 3 次，实际 $(cat "$w/cnt")"; exit 1; }
echo "✓ sha256 不符：重试 3 次后失败，不留文件"
# 3) 一直断 → 失败
rm -f "$w/cnt"*
if FAILS=99 BODY=x FETCH_TRIES=2 run >/dev/null 2>&1; then echo "✗ 一直断竟然成功"; exit 1; fi
[ ! -e "$f" ] || { echo "✗ 留下了文件"; exit 1; }
echo "✓ 持续断网：失败退出"
# 4) workflow 缓存 key 必须跟脚本里锁定的 sha 一致（改版本忘改 key 会缓存旧包）
sha=$(sed -n 's/^M0PACK_SHA=\([0-9a-f]*\).*/\1/p' "$root/tools/fetch_third_party.sh")
grep -q "key: m0pack-.*-$sha" "$root/.github/workflows/app-windows.yml" || { echo "✗ app-windows.yml m0pack 缓存 key 与 M0PACK_SHA 不一致"; exit 1; }
echo "✓ m0pack 缓存 key 与锁定 sha 一致"
