#!/bin/bash
# UdemyBar.app 重建脚本 — 修改源码后运行此脚本
# 用法: cd ~/Downloads/codex && ./rebuild_app.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/UdemyBar.app"
RES="$APP/Contents/Resources"
MACOS="$APP/Contents/MacOS"

echo ">>> 停止旧进程..."
pkill -f "udemy_bar.py" 2>/dev/null || true
sleep 1

echo ">>> 清理旧 .app..."
rm -rf "$APP"

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
    <string>com.kengong.udemybar</string>
    <key>CFBundleName</key>
    <string>UdemyBar</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>2</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

# ---- 可执行文件：直接用 Python 脚本（带 shebang）----
echo ">>> 创建可执行文件..."
cat > "$MACOS/UdemyBar" << 'PYEOF'
#!/usr/bin/python3
import sys, os, traceback
# 设置脚本路径
_res = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Resources")
_res = os.path.normpath(_res)
sys.path.insert(0, _res)
os.chdir(_res)
# 日志函数
def _log(msg):
    try:
        with open("/tmp/udemybar_debug.log", "a") as f:
            f.write(str(msg) + "\n")
    except: pass
_log("Launcher started")
_log(f"Python: {sys.executable}")
_log(f"Resources: {_res}")
_log(f"sys.path: {sys.path[:3]}")
try:
    from udemy_bar import main
    _log("udemy_bar imported OK")
    main()
except Exception as e:
    _log(f"FATAL: {e}")
    _log(traceback.format_exc())
PYEOF
chmod +x "$MACOS/UdemyBar"

# ---- 复制源码和资源 ----
echo ">>> 复制源码到 .app..."
cp "$SCRIPT_DIR/udemy_bar.py"     "$RES/"
cp "$SCRIPT_DIR/udemy_watch.py"   "$RES/"
cp "$SCRIPT_DIR/fetch_courses.py" "$RES/"
cp "$SCRIPT_DIR/play.png"         "$RES/" 2>/dev/null || true
cp "$SCRIPT_DIR/stop.png"         "$RES/" 2>/dev/null || true
chmod +x "$RES/udemy_bar.py" "$RES/udemy_watch.py"

# ---- 清除隔离标记 ----
echo ">>> 清除隔离标记..."
xattr -cr "$APP" 2>/dev/null || true

# ---- Ad-hoc 签名 ----
echo ">>> 代码签名..."
codesign --force --deep --sign - "$APP" 2>/dev/null || true

# ---- 刷新 Launch Services ----
echo ">>> 刷新 Launch Services..."
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "$APP" 2>/dev/null || true

# ---- 启动 ----
echo ">>> 启动应用..."
open "$APP"
sleep 3

# ---- 验证 ----
if pgrep -f "UdemyBar" > /dev/null 2>&1; then
    echo ""
    echo "✅ App 已启动！进程运行中。"
    echo "📋 Debug 日志: /tmp/udemybar_debug.log"
    echo "📋 菜单栏应显示 '▶ Udemy' 文字"
else
    echo ""
    echo "⚠️  App 可能未成功启动，检查日志: /tmp/udemybar_debug.log"
fi
