# Udemy AutoWatch

macOS 菜单栏应用，自动观看 Udemy 课程视频并标记完成。

## 功能

- **自动播放**：以 2x 倍速观看视频，播完自动跳到下一节
- **自动跳过**：遇到无视频章节（资源下载、文档等）自动标记完成并跳过
- **课程选择**：菜单栏列出所有已注册课程，点哪个刷哪个
- **进度追踪**：记录月度刷课时长和已完成的章节
- **日志记录**：每个操作（标记完成、跳转、导航）都写入日志文件

## 截图

菜单栏点击 Udemy 图标，选择课程列表中你想刷的课程即可。

## 安装

### 依赖

```bash
# Python 3.9+ (macOS 自带)
python3 --version

# Playwright
pip3 install playwright rumps
python3 -m playwright install chromium

# rumps (菜单栏应用)
pip3 install rumps
```

### 配置

1. **首次登录**：首次运行时会打开浏览器，手动登录你的 Udemy 账号。登录后浏览器 profile 会保存在 `~/Library/Application Support/Udemy-AutoWatch-Chrome/`，后续运行免登录。

2. **修改域名**：编辑 `udemy_watch.py` 和 `fetch_courses.py`，将 `your-org.udemy.com` 替换为你的 Udemy Business 域名（或 `www.udemy.com`）。

## 使用

### 方式一：菜单栏应用（推荐）

```bash
cd udemy-autowatch
python3 udemy_bar.py
```

菜单栏出现 Udemy 图标后：
- **▶ 开始刷课** — 从上次的位置继续
- **⏹ 停止** — 停止当前刷课
- **📚 课程列表** — 选择要刷的课程
- **🔄 刷新课程列表** — 重新抓取已注册课程
- **📊 月度统计** — 查看本月刷课时长

### 方式二：命令行

```bash
# 刷 2 小时，2x 倍速
python3 udemy_watch.py --hours 2 --rate 2.0

# 从指定课程开始
python3 udemy_watch.py --resume "https://your-org.udemy.com/course-dashboard-redirect/?course_id=XXXX"

# 查看月度统计
python3 udemy_watch.py --summary
```

### 方式三：打包为 .app

```bash
./rebuild_app.sh
```

生成 `UdemyBar.app`，可以拖到 `/Applications/` 使用。

## 文件说明

| 文件 | 说明 |
|------|------|
| `udemy_watch.py` | 核心刷课逻辑（Playwright 自动化） |
| `udemy_bar.py` | macOS 菜单栏应用（rumps） |
| `fetch_courses.py` | 课程列表抓取脚本 |
| `rebuild_app.sh` | 一键重建 .app bundle |
| `udemy-watch.sh` | 命令行快捷脚本 |
| `launch_bar.sh` | 启动菜单栏应用 |

## 技术要点

- **React 事件处理**：Udemy 页面用 React，对 `<div>` 等非交互元素必须用 `dispatchEvent(new MouseEvent('click', ...))` 而不是 `.click()`
- **多语言支持**：同时匹配中文（"标记为完成"）和英文（"Mark as complete"）
- **5 步跳过策略**：标记完成 → 点击 Next → 键盘快捷键 → 侧边栏点击 → 强制 URL 导航
- **浏览器 profile 复用**：用独立的 Chrome profile 保存登录状态，避免每次都要登录

## 本地文件

运行后会在 home 目录生成以下文件：

| 文件 | 说明 |
|------|------|
| `~/udemy_watch_state.json` | 当前播放位置 |
| `~/udemy_watch_log.jsonl` | 操作日志 |
| `~/udemy_courses.json` | 课程列表缓存 |

## License

MIT
