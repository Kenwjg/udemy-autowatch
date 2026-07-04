#!/bin/bash
# 快捷刷课脚本
# 使用方法:
#   ./udemy-watch.sh               # 默认刷1小时
#   ./udemy-watch.sh 2             # 刷2小时
#   ./udemy-watch.sh 30 1.5        # 刷30小时(1.5倍速，实际20小时)
#   ./udemy-watch.sh status        # 查看月度统计
#   ./udemy-watch.sh resume URL    # 指定课程续播
#   ./udemy-watch.sh course URL H  # 指定课程刷课

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/udemy_watch.py"

if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "错误: 找不到 $PYTHON_SCRIPT"
    exit 1
fi

case "$1" in
    status|summary|--summary)
        python3 "$PYTHON_SCRIPT" --summary
        ;;
    resume)
        URL="${2}"
        python3 "$PYTHON_SCRIPT" --resume "$URL" --rate "${3:-2.0}"
        ;;
    course)
        URL="${2}"
        HOURS="${3:-1}"
        RATE="${4:-1.0}"
        echo "指定课程: $URL，刷课 ${HOURS}h，${RATE}x 倍速"
        python3 "$PYTHON_SCRIPT" --course "$URL" --hours "$HOURS" --rate "$RATE"
        ;;
    help|--help|-h)
        python3 "$PYTHON_SCRIPT" --help
        ;;
    *)
        HOURS="${1:-1}"
        RATE="${2:-1.0}"
        echo "刷课 ${HOURS} 小时，${RATE}x 倍速"
        echo "按 Ctrl+C 可随时停止"
        echo ""
        python3 "$PYTHON_SCRIPT" --hours "$HOURS" --rate "$RATE"
        ;;
esac
