#!/bin/bash
# 启动 UdemyBar 菜单栏应用
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 如果 .app 存在，直接启动
if [ -d "$SCRIPT_DIR/UdemyBar.app" ]; then
    open "$SCRIPT_DIR/UdemyBar.app"
    echo "UdemyBar 已启动"
else
    # 降级：直接运行 Python 脚本
    /usr/bin/python3 "$SCRIPT_DIR/udemy_bar.py"
fi
