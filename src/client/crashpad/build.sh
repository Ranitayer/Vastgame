#!/usr/bin/env bash
# Build the CMake-enabled upstream Crashpad fork; never run during VM startup.
set -euo pipefail
source_dir="${1:?Usage: build.sh <checkout> <build-dir> <install-dir>}"
build_dir="${2:?}"
install_dir="${3:?}"
revision=eb5fa6e8576e79113b21296bd6af7e2a542839db
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$revision" ]] || {
  echo 'Unexpected Crashpad revision' >&2; exit 1;
}
cmake -S "$(dirname "$0")" -B "$build_dir" -G Ninja \
  -DCRASHPAD_SOURCE="$source_dir" -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir" --target vastgame_crashpad crashpad_handler --parallel 4
install -d -m 700 "$install_dir"
install -m 755 "$build_dir/vastgame_crashpad.so" "$install_dir/vastgame_crashpad.so"
install -m 755 "$build_dir/crashpad/handler/crashpad_handler" "$install_dir/crashpad_handler"
# Upstream license files accompany the binaries.
install -m 644 "$source_dir/LICENSE" "$install_dir/CRASHPAD-LICENSE"
install -m 644 "$source_dir/third_party/mini_chromium/mini_chromium/LICENSE" "$install_dir/MINI-CHROMIUM-LICENSE"
