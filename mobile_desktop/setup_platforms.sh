#!/usr/bin/env bash
# Generate Flutter platform directories (android/ios/macos/windows).
# Run this once after cloning when you have Flutter SDK installed.
#
# Prerequisites:
#   - Flutter SDK 3.16+ (https://flutter.dev/docs/get-started/install)
#   - For iOS: Xcode 15+
#   - For Android: Android Studio + SDK
#   - For macOS: Xcode 15+
#   - For Windows: Visual Studio 2022 + C++ Desktop workload

set -e
cd "$(dirname "$0")"

if ! command -v flutter &>/dev/null; then
    echo "ERROR: flutter not found. Install Flutter SDK first."
    echo "  https://flutter.dev/docs/get-started/install"
    exit 1
fi

echo "Flutter version:"
flutter --version

BACKUP_DIR=$(mktemp -d)
echo "Backing up lib/ and pubspec.yaml to $BACKUP_DIR ..."
cp -r lib "$BACKUP_DIR/"
cp pubspec.yaml "$BACKUP_DIR/"
cp -r assets "$BACKUP_DIR/" 2>/dev/null || true

TEMP_DIR=$(mktemp -d)
echo "Creating temp Flutter project in $TEMP_DIR ..."
flutter create --org com.agentpilot --project-name agent_pilot "$TEMP_DIR/agent_pilot"

for platform in android ios macos windows linux web; do
    SRC="$TEMP_DIR/agent_pilot/$platform"
    if [ -d "$SRC" ]; then
        if [ -d "$platform" ]; then
            echo "  $platform/ already exists, skipping."
        else
            echo "  Copying $platform/ ..."
            cp -r "$SRC" .
        fi
    fi
done

echo "Restoring lib/ and pubspec.yaml ..."
rm -rf lib
cp -r "$BACKUP_DIR/lib" .
cp "$BACKUP_DIR/pubspec.yaml" .
cp -r "$BACKUP_DIR/assets" . 2>/dev/null || true

rm -rf "$TEMP_DIR" "$BACKUP_DIR"

echo ""
echo "Resolving dependencies ..."
flutter pub get

echo ""
echo "Platform directories generated. Try:"
echo "  flutter run -d macos"
echo "  flutter run -d chrome"
echo "  flutter build apk"
