#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly FVCORE_DIR="$ROOT_DIR/fvcore"
readonly FVCORE_BIN="$FVCORE_DIR/target/debug/fvcore"
readonly FVCORE_CONFIG="$FVCORE_DIR/target/debug/config.json"

log() {
  printf '[core] %s\n' "$*"
}

fail() {
  printf '[core] 错误：%s\n' "$*" >&2
  exit 1
}

command -v cargo >/dev/null 2>&1 || fail "找不到 cargo"
[[ -f "$FVCORE_DIR/Cargo.toml" ]] || fail "缺少 $FVCORE_DIR/Cargo.toml"

log "构建 fvcore……"
cargo build --manifest-path "$FVCORE_DIR/Cargo.toml" --bin fvcore
[[ -x "$FVCORE_BIN" ]] || fail "fvcore 构建后仍不可执行：$FVCORE_BIN"

if [[ ! -f "$FVCORE_CONFIG" ]]; then
  log "创建默认配置 $FVCORE_CONFIG……"
  "$FVCORE_BIN" create-config
fi

log "启动 fvcore web（默认地址 http://127.0.0.1:8787）"
exec "$FVCORE_BIN" web "$@"
