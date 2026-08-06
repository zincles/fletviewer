#!/usr/bin/env bash
# 重新生成 flutter_rust_bridge 桥代码（Rust facade -> Dart）。
# Rust API 变更后必须运行本脚本，否则 start.sh 会拒绝启动。
set -Eeuo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly FRONTEND_DIR="$ROOT_DIR/frontend"

fail() {
  printf '[codegen] 错误：%s\n' "$*" >&2
  exit 1
}

resolve_codegen() {
  local candidates=(
    "$HOME/.cargo/bin/flutter_rust_bridge_codegen"
    "$(command -v flutter_rust_bridge_codegen 2>/dev/null || true)"
  )
  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  fail "找不到 flutter_rust_bridge_codegen；请先 cargo install flutter_rust_bridge_codegen@2.12.0"
}

codegen_bin="$(resolve_codegen)"
printf '[codegen] 重新生成 FRB 桥代码（--no-web，WASM 非本轮目标）\n'
cd -- "$FRONTEND_DIR"
"$codegen_bin" generate \
  --rust-input crate::api \
  --rust-root ../fvcore \
  --dart-output lib/src/rust \
  --no-web
rm -f lib/src/rust/frb_generated.web.dart
printf '[codegen] 格式化 Rust 生成物\n'
cd -- "$ROOT_DIR/fvcore"
cargo fmt --all
printf '[codegen] 完成；两侧 content hash 已同步，可直接 ./start.sh\n'
