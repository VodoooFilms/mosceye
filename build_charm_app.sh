#!/bin/sh
# Native macOS preview; the actual simulator remains the implementation.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUILD="$HERE/../muse-gadget-sdk/esp32/simulator/build"
cmake --build "$BUILD" --parallel
APP="$HERE/MOSCEYE Charm.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/muse_simulator" "$APP/Contents/MacOS/mosceye-charm"
cp "$HERE/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>mosceye-charm</string>
<key>CFBundleIdentifier</key><string>ai.hackathon.mosceye.charm</string>
<key>CFBundleName</key><string>MOSCEYE Charm</string>
<key>CFBundleDisplayName</key><string>MOSCEYE Charm</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>2</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSMicrophoneUsageDescription</key><string>Grabar un mensaje de voz para compartirlo con el cajero por WhatsApp.</string>
<key>LSEnvironment</key><dict><key>MOSCEYE_RETAIL</key><string>1</string></dict>
</dict></plist>
PLIST
