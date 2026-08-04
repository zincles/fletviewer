#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly FRONTEND_DIR="$ROOT_DIR/frontend"

fail() {
  printf '[frontend] 错误：%s\n' "$*" >&2
  exit 1
}

resolve_flutter() {
  if [[ -n "${FLUTTER_BIN:-}" ]]; then
    [[ -x "$FLUTTER_BIN" ]] || fail "FLUTTER_BIN 不可执行：$FLUTTER_BIN"
    printf '%s\n' "$FLUTTER_BIN"
    return
  fi

  if command -v flutter >/dev/null 2>&1; then
    command -v flutter
    return
  fi

  local bundled="$HOME/flutter/3.41.7/bin/flutter"
  [[ -x "$bundled" ]] || fail "找不到 Flutter；请设置 FLUTTER_BIN 或把 flutter 加入 PATH"
  printf '%s\n' "$bundled"
}

[[ -d "$FRONTEND_DIR" ]] || fail "缺少 Flutter 工程：$FRONTEND_DIR"

flutter_bin="$(resolve_flutter)"
device="${FLUTTER_DEVICE:-linux}"
printf '[frontend] 启动 Flutter（device: %s）\n' "$device"
cd -- "$FRONTEND_DIR"
exec "$flutter_bin" run -d "$device" "$@"
