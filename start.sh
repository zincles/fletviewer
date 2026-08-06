#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly FRONTEND_DIR="$ROOT_DIR/frontend"
readonly BUNDLE_DIR="$FRONTEND_DIR/build/linux/x64/release/bundle"
readonly FRONTEND_BIN="$BUNDLE_DIR/fletviewer_frontend"
readonly APP_PATTERN="fletviewer_frontend"

fail() {
  printf '[start] 错误：%s\n' "$*" >&2
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

restart="${FVCORE_RESTART:-0}"
if [[ "${1:-}" == "--restart" ]]; then
  restart=1
  shift
fi

check_bridge_sync() {
  local rust_hash dart_hash
  rust_hash="$(sed -n 's/.*FLUTTER_RUST_BRIDGE_CODEGEN_CONTENT_HASH: i32 = \(-*[0-9]*\);/\1/p' "$ROOT_DIR/fvcore/src/frb_generated.rs" | head -1)"
  dart_hash="$(sed -n 's/.*int get rustContentHash => \(-*[0-9]*\);/\1/p' "$FRONTEND_DIR/lib/src/rust/frb_generated.dart" | head -1)"
  if [[ -z "$rust_hash" || -z "$dart_hash" || "$rust_hash" != "$dart_hash" ]]; then
    printf '[start] 错误：FRB 桥代码不同步（Rust=%s Dart=%s），会导致 Runtime 启动失败。\n' "${rust_hash:-?}" "${dart_hash:-?}"
    printf '[start] 请先运行 ./codegen.sh 重新生成桥代码，再重新启动。\n'
    exit 1
  fi
}

check_bridge_sync

force_rebuild_rust_if_stale() {
  local generated mtime libs stale
  generated="$(stat -c %Y "$ROOT_DIR/fvcore/src/frb_generated.rs" 2>/dev/null || echo 0)"
  libs="$(find "$FRONTEND_DIR/build" -path "*plugins/fvcore/cargokit_build*/release/deps/libfvcore.so" 2>/dev/null || true)"
  [[ -z "$libs" ]] && return 0
  stale=0
  for lib in $libs; do
    mtime="$(stat -c %Y "$lib" 2>/dev/null || echo 0)"
    if [[ "$mtime" -lt "$generated" ]]; then
      stale=1
      break
    fi
  done
  if [[ "$stale" == "1" ]]; then
    printf '[start] 桥代码更新于 Rust 产物之后，清理 cargokit 缓存以强制重编（首次较慢）\n'
    rm -rf \
      "$FRONTEND_DIR/build/linux/x64/release/plugins/fvcore/cargokit_build" \
      "$FRONTEND_DIR/build/linux/x64/debug/plugins/fvcore/cargokit_build"
  fi
}

force_rebuild_rust_if_stale

if [[ "$restart" == "1" ]]; then
  local_pids="$(pgrep -f "$APP_PATTERN" 2>/dev/null || true)"
  if [[ -n "$local_pids" ]]; then
    printf '[start] --restart：停止既有实例（PID %s）\n' "$(printf '%s' "$local_pids" | tr '\n' ' ')"
    # 只清理本应用同名进程，不触碰其他 fvcore 进程（如独立 server）。
    kill $local_pids 2>/dev/null || true
    for _ in $(seq 1 20); do
      pgrep -f "$APP_PATTERN" >/dev/null 2>&1 || break
      sleep 0.25
    done
    kill -9 $local_pids 2>/dev/null || true
  fi
else
  existing="$(pgrep -f "$APP_PATTERN" 2>/dev/null || true)"
  if [[ -n "$existing" ]]; then
    printf '[start] 检测到已有实例正在运行（PID %s）。\n' "$(printf '%s' "$existing" | tr '\n' ' ')"
    printf '[start] 请先关闭它再启动，或使用 ./start.sh --restart 自动重启（仅清理本应用同名进程）。\n'
    exit 1
  fi
fi

[[ -d "$FRONTEND_DIR" ]] || fail "缺少 Flutter 工程：$FRONTEND_DIR"

flutter_bin="$(resolve_flutter)"
printf '[start] 构建 Flutter Linux release；fvcore 由 flutter_rust_bridge 一并编译并嵌入应用进程\n'
cd -- "$FRONTEND_DIR"
"$flutter_bin" build linux --release
[[ -x "$FRONTEND_BIN" ]] || fail "缺少构建产物：$FRONTEND_BIN"
printf '[start] 启动 release bundle\n'
exec "$FRONTEND_BIN" "$@"
