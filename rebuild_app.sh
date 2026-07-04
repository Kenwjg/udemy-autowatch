#!/bin/bash
# UdemyBar.app 重建脚本 — 修改源码后运行此脚本
# 用法: cd ~/Downloads/codex && ./rebuild_app.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$SCRIPT_DIR/UdemyBar.app"
RES="$APP/Contents/Resources"
MACOS="$APP/Contents/MacOS"

echo ">>> 停止旧进程..."
pkill -f "udemy_bar.py" 2>/dev/null || true
sleep 1

echo ">>> 创建 .app 结构..."
mkdir -p "$RES" "$MACOS"

# ---- PkgInfo ----
printf 'APPL????' > "$APP/Contents/PkgInfo"

# ---- Info.plist ----
cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>UdemyBar</string>
    <key>CFBundleIdentifier</key>
    <string>com.example.udemybar</string>
    <key>CFBundleName</key>
    <string>UdemyBar</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
PLIST

# ---- Launcher ----
cat > "$MACOS/UdemyBar" << 'LAUNCHER'
#!/bin/bash
# UdemyBar — 从 .app bundle 内部加载脚本
APP_RESOURCES="$(cd "$(dirname "$0")/../Resources" 2>/dev/null && pwd)"
MAIN_SCRIPT="$APP_RESOURCES/udemy_bar.py"
if [ ! -f "$MAIN_SCRIPT" ]; then
    for candidate in "$HOME/Downloads/codex" "$HOME/codex"; do
        if [ -f "$candidate/udemy_bar.py" ]; then
            APP_RESOURCES="$candidate"
            MAIN_SCRIPT="$APP_RESOURCES/udemy_bar.py"
            break
        fi
    done
fi
cd "$APP_RESOURCES" 2>/dev/null
exec /usr/bin/python3 "$MAIN_SCRIPT" 2>> /tmp/udemybar_debug.log
LAUNCHER
chmod +x "$MACOS/UdemyBar"

# ---- 复制源码和资源 ----
echo ">>> 复制源码到 .app..."
cp "$SCRIPT_DIR/udemy_bar.py"   "$RES/"
cp "$SCRIPT_DIR/udemy_watch.py" "$RES/"
cp "$SCRIPT_DIR/play.png"       "$RES/" 2>/dev/null || echo "  ⚠ play.png 缺失"
cp "$SCRIPT_DIR/stop.png"       "$RES/" 2>/dev/null || echo "  ⚠ stop.png 缺失"
chmod +x "$RES/udemy_bar.py" "$RES/udemy_watch.py"

# ---- Ad-hoc 签名 ----
echo ">>> 代码签名..."
codesign --force --deep --sign - "$APP"

# ---- 启动 ----
echo ">>> 启动应用..."
open "$APP"

echo ""
echo "✅ 完成！菜单栏应出现 Udemy 图标。"
