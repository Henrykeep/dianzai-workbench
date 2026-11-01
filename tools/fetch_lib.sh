#!/usr/bin/env bash
# 共用下载助手（fetch_third_party.sh、package_windows.sh 都 source 它）
# 带重试 + sha256 校验的下载（CI run 41199129663：m0pack curl exit 56 连接被断）。
#   fetch_url <url> <输出文件> <sha256>
# curl 自身重试（指数退避；支持时加 --retry-all-errors，覆盖 exit 56 这类非 HTTP 瞬断），外面再套 N 次整体重试。
# sha 不符视为下载坏了，也重试；N 次仍不符 → 失败，绝不留下坏文件。
FETCH_TRIES=${FETCH_TRIES:-4}; FETCH_SLEEP=${FETCH_SLEEP:-5}
fetch_url() {
  local url=$1 out=$2 sha=$3 i opts=(-fsSL --connect-timeout 30 --retry 5 --retry-delay 2 --retry-connrefused)
  [[ "$(curl --help all 2>/dev/null || true)" == *--retry-all-errors* ]] && opts+=(--retry-all-errors)
  for ((i=1; i<=FETCH_TRIES; i++)); do
    rm -f "$out.tmp"
    if curl "${opts[@]}" -o "$out.tmp" "$url"; then
      if echo "$sha  $out.tmp" | sha256sum -c - >/dev/null 2>&1; then mv "$out.tmp" "$out"; return 0; fi
      echo "✗ [fetch] $(basename "$out") sha256 不符（第 $i/$FETCH_TRIES 次）"
    else
      echo "✗ [fetch] $(basename "$out") 下载失败 exit $?（第 $i/$FETCH_TRIES 次）"
    fi
    [ $i -lt $FETCH_TRIES ] && sleep $((FETCH_SLEEP * i))
  done
  rm -f "$out.tmp"; echo "✗ [fetch] $url 重试 $FETCH_TRIES 次仍失败 · 处理：检查网络后重跑 make fetch"; return 1
}
