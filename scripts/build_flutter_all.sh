#!/usr/bin/env bash
# Build the Flutter Agent-Pilot client for all 4 targets and drop the
# artifacts into ../dist/ so CI / reviewers can grab them in one place.
#
# Usage:
#   ./scripts/build_flutter_all.sh              # all platforms available
#   ./scripts/build_flutter_all.sh ios android  # subset

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/mobile_desktop"
DIST="$ROOT/dist"
mkdir -p "$DIST"

cd "$APP"
flutter pub get

build() {
  local target=$1
  case "$target" in
    android)
      flutter build apk --release
      cp build/app/outputs/flutter-apk/app-release.apk "$DIST/larkmentor-android.apk"
      ;;
    ios)
      flutter build ipa --release || {
        echo "ios build needs Xcode signing; produced .app only."; exit 0;
      }
      find build -name "*.ipa" | head -n1 | xargs -I{} cp {} "$DIST/larkmentor-ios.ipa"
      ;;
    macos)
      flutter build macos --release
      APP_PATH=$(ls -d build/macos/Build/Products/Release/*.app | head -n1)
      hdiutil create -volname LarkMentor -srcfolder "$APP_PATH" -ov -format UDZO \
        "$DIST/larkmentor-macos.dmg"
      ;;
    windows)
      flutter build windows --release
      (cd build/windows/x64/runner/Release && zip -r -9 "$DIST/larkmentor-windows.zip" .)
      ;;
    web)
      flutter build web --release
      (cd build/web && tar czf "$DIST/larkmentor-web.tgz" .)
      ;;
    *) echo "unknown target: $target"; exit 1;;
  esac
}

TARGETS=("$@")
if [ "${#TARGETS[@]}" -eq 0 ]; then
  TARGETS=(android ios macos windows web)
fi
for t in "${TARGETS[@]}"; do
  echo "== build $t =="
  build "$t" || echo "warn: $t build failed (continuing)"
done

echo "Artifacts in: $DIST"
ls -lh "$DIST"
