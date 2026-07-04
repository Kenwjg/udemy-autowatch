#!/usr/bin/env python3
"""
Udemy 刷课 - macOS 菜单栏（增强版）
支持进度条、课程进度/剩余/总时长统计
"""
import json, os, subprocess, sys, re, traceback
from datetime import datetime
from collections import defaultdict
import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_LOG = "/tmp/udemybar_debug.log"

def _debug(msg):
    """写入调试日志"""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except:
        pass

def _find_icon(name):
    p = os.path.join(SCRIPT_DIR, name)
    if os.path.exists(p): return p
    p2 = os.path.expanduser(f"~/udemy_icons/{name}")
    if os.path.exists(p2): return p2
    return None

ICON_PLAY = _find_icon("play.png")
ICON_STOP = _find_icon("stop.png")

WATCH_SCRIPT = os.path.join(SCRIPT_DIR, "udemy_watch.py")
FETCH_SCRIPT = os.path.join(SCRIPT_DIR, "fetch_courses.py")
LOG_FILE = os.path.expanduser("~/udemy_watch_log.jsonl")
TARGET_FILE = os.path.expanduser("~/udemy_target_hours.json")
COURSES_FILE = os.path.expanduser("~/udemy_courses.json")

# ── 进度条配置 ──
BAR_WIDTH = 10  # 进度条宽度（字符数）

def _progress_bar(current, target):
    """返回 Unicode 进度条字符串，如 '████████░░ 8.5h/30h (28%)'"""
    pct = min(current / target, 1.0) if target > 0 else 0
    filled = int(pct * BAR_WIDTH)
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    return f"{bar} {current:.1f}h/{target}h ({pct*100:.0f}%)"

def _fmt_dur(seconds):
    """格式化秒数为可读字符串"""
    if seconds < 60: return f"{int(seconds)}s"
    if seconds < 3600: return f"{int(seconds/60)}m"
    return f"{seconds/3600:.1f}h"

# ── 数据加载 ──

def load_logs():
    if not os.path.exists(LOG_FILE): return []
    entries = []
    with open(LOG_FILE) as f:
        for line in f:
            try: entries.append(json.loads(line.strip()))
            except: pass
    return sorted(entries, key=lambda e: e.get("ts", ""), reverse=True)


def load_target():
    if os.path.exists(TARGET_FILE):
        try: return json.load(open(TARGET_FILE))["target"]
        except: pass
    return 30


def save_target(h):
    json.dump({"target": h}, open(TARGET_FILE, "w"))


def load_courses():
    if os.path.exists(COURSES_FILE):
        try:
            data = json.load(open(COURSES_FILE))
            if isinstance(data, dict) and "courses" in data:
                return data
        except: pass
    return {"courses": [], "fetched_at": "", "count": 0}


# ── 统计 ──

def monthly_hours(entries):
    now = datetime.now()
    ms = datetime(now.year, now.month, 1)
    me = datetime(now.year + 1, 1, 1) if now.month == 12 else datetime(now.year, now.month + 1, 1)
    return sum(e["dur"] for e in entries
               if ms <= datetime.fromisoformat(e["ts"]) < me and e["status"] == "done") / 3600


def total_hours(entries):
    return sum(e["dur"] for e in entries if e["status"] == "done") / 3600


def course_log_stats(entries):
    """从日志中按课程名聚合统计。
    返回 {course_name: {count, skipped_count, total_dur, url, last_ts}}"""
    stats = {}
    for e in entries:
        if e["status"] != "done": continue
        cn = e.get("course_name", "").strip()
        cu = e.get("course_url", "").strip()
        if not cn:
            cn = "(未分类)"
        if cn not in stats:
            stats[cn] = {"count": 0, "skipped": 0, "total_dur": 0, "url": cu, "last_ts": e["ts"]}
        stats[cn]["count"] += 1
        if e.get("skip"):
            stats[cn]["skipped"] += 1
        stats[cn]["total_dur"] += e["dur"]
        if e["ts"] > stats[cn]["last_ts"]:
            stats[cn]["last_ts"] = e["ts"]
            if cu:
                stats[cn]["url"] = cu
    return stats


def monthly_breakdown(entries):
    bc = {}
    for e in entries:
        if e["status"] != "done": continue
        k = datetime.fromisoformat(e["ts"]).strftime("%Y-%m")
        bc[k] = bc.get(k, 0) + e["dur"] / 3600
    return dict(sorted(bc.items()))


def _match_course_by_name(fetch_name, log_cnames):
    """模糊匹配课程名：检查是否包含关键部分"""
    fn = fetch_name.strip().lower()
    # 去除特殊字符后的纯文本匹配
    fn_clean = re.sub(r'[\s\-\.\(\),;:!！：；（）]', '', fn)
    for log_name in log_cnames:
        ln = log_name.strip().lower()
        ln_clean = re.sub(r'[\s\-\.\(\),;:!！：；（）]', '', ln)
        # 精确匹配
        if fn == ln: return log_name
        if fn_clean == ln_clean: return log_name
        # 包含匹配（一方包含另一方）
        if len(fn_clean) > 6 and fn_clean in ln_clean: return log_name
        if len(ln_clean) > 6 and ln_clean in fn_clean: return log_name
    return None


def enriched_courses(entries):
    """将 fetch 课程数据与刷课日志交叉关联，返回增强后的课程列表。
    每门课程包含: name, url, progress%, watched_lectures, total_lectures,
    watched_time, total_hours, remaining_lectures, remaining_time
    """
    courses_data = load_courses()
    raw_courses = courses_data.get("courses", [])
    log_stats = course_log_stats(entries)
    log_cnames = list(log_stats.keys())

    enriched = []
    for c in raw_courses:
        cname = c.get("name", "(未知)")
        curl = c.get("url", "")
        progress = c.get("progress", "")
        total_lec = c.get("lectures_total", "")
        total_hrs = c.get("total_hours", "")

        # 匹配日志中的课程统计
        matched_log_name = _match_course_by_name(cname, log_cnames)
        log_s = log_stats.get(matched_log_name) if matched_log_name else None

        watched_lec = 0
        skipped_lec = 0
        watched_dur = 0
        if log_s:
            watched_lec = log_s["count"]
            skipped_lec = log_s.get("skipped", 0)
            watched_dur = log_s["total_dur"]

        # 计算进度（优先用抓取到的 progress%，其次根据节数估算）
        progress_pct = 0
        if progress:
            try:
                progress_pct = int(progress)
            except:
                pass
        elif total_lec:
            try:
                progress_pct = int(watched_lec / int(total_lec) * 100)
            except:
                pass

        # 剩余
        remaining_lec = ""
        if total_lec:
            try:
                remaining_lec = str(int(total_lec) - watched_lec)
            except:
                pass

        remaining_time = ""
        if total_hrs:
            try:
                remaining_time = max(float(total_hrs) * 3600 - watched_dur, 0)
            except:
                pass

        enriched.append({
            "name": cname,
            "url": curl,
            "progress_pct": progress_pct,
            "progress_raw": progress,
            "watched_lec": watched_lec,
            "skipped_lec": skipped_lec,
            "total_lec": total_lec,
            "watched_dur": watched_dur,
            "total_hrs": total_hrs,
            "remaining_lec": remaining_lec,
            "remaining_time": remaining_time,
        })

    # 处理日志中存在但 fetch 没有的课程（比如名字不匹配的）
    matched_fetch_names = set()
    for ec in enriched:
        matched_log_name = _match_course_by_name(ec["name"], log_cnames)
        if matched_log_name:
            matched_fetch_names.add(matched_log_name)

    for log_name, log_s in log_stats.items():
        if log_name in matched_fetch_names or log_name == "(未分类)":
            continue
        enriched.append({
            "name": log_name,
            "url": log_s.get("url", ""),
            "progress_pct": 0,
            "progress_raw": "",
            "watched_lec": log_s["count"],
            "skipped_lec": log_s.get("skipped", 0),
            "total_lec": "",
            "watched_dur": log_s["total_dur"],
            "total_hrs": "",
            "remaining_lec": "",
            "remaining_time": "",
        })

    # 排序：有进度的在前面，按进度排序；没进度的在后面
    enriched.sort(key=lambda x: (-x["progress_pct"], -x["watched_dur"]))

    return enriched


# ── 主 App ──

class UdemyBarApp(rumps.App):
    def __init__(self):
        _debug("App __init__ 开始")
        super(UdemyBarApp, self).__init__(
            "UdemyBar",
            title="▶ Udemy",
            quit_button=None,
        )
        _debug("super().__init__ 完成")
        self._watch_proc = None
        # 防崩溃：_build_menu 失败不影响状态栏图标
        try:
            self._build_menu()
            _debug("_build_menu 完成")
        except Exception as e:
            _debug(f"_build_menu 失败: {e}")
            self.menu = ["▶ 开始刷课", None, "退出"]
        # 启动通知放到 timer 里，不在 __init__ 直接调
        rumps.Timer(self._startup_notify, 1).start()

    def _startup_notify(self, _):
        """延迟1秒弹窗，确保 app 已完全启动"""
        if hasattr(self, '_notified'):
            return
        self._notified = True
        try:
            rumps.notification("Udemy 刷课", "已启动", "菜单栏显示 '▶ Udemy'", sound=False)
            _debug("通知已发送")
            # 弹窗让用户看到 app 已启动
            rumps.alert(
                title="Udemy 刷课已启动",
                message="App 正在运行！\n\n"
                        "👉 点击屏幕顶部菜单栏的 '▶ Udemy' 文字\n"
                        "   可以开始刷课、查看进度、选择课程\n\n"
                        "👉 App 图标也在 Dock 中显示\n\n"
                        "如果菜单栏看不到，可能被其他图标挤到折叠区了，\n"
                        "按住 Cmd 拖动可以调整位置。",
                ok="知道了",
                cancel=None
            )
            _debug("启动弹窗已显示")
        except Exception as e:
            _debug(f"启动通知失败: {e}")
            _debug(traceback.format_exc())
        # 停止这个一次性 timer
        try:
            self._startup_notify_timer.stop()
        except:
            pass

    def _build_menu(self):
        self.menu.clear()
        try:
            entries = load_logs()
            tg = load_target()
            mn = monthly_hours(entries)
            tt = total_hours(entries)
        except Exception as e:
            _debug(f"数据加载失败: {e}")
            entries, tg, mn, tt = [], 30, 0, 0

        running = self._watch_proc is not None and self._watch_proc.poll() is None

        if running:
            self.title = "⏹ Udemy"
        else:
            self.title = "▶ Udemy"

        # ── 开始/停止刷课 ──
        if running:
            self.menu.add(rumps.MenuItem("⏹ 停止刷课", callback=self.stop_watch))
            self.menu.add(rumps.MenuItem("● 运行中...", callback=None))
        else:
            self.menu.add(rumps.MenuItem("▶ 开始刷课", callback=self.start_watch))

        self.menu.add(rumps.separator)

        # ── 进度条 ──
        bar_text = _progress_bar(mn, tg)
        self.menu.add(rumps.MenuItem(f"📊 {bar_text}", callback=None))
        if running:
            self.menu.add(rumps.MenuItem("  (刷课中，每10秒刷新)", callback=None))

        self.menu.add(rumps.separator)

        # ── 课程列表（增强：进度/剩余/时长） ──
        enriched = enriched_courses(entries)
        courses_menu = rumps.MenuItem("📚 课程列表")
        courses_menu.add(rumps.MenuItem("🔄 刷新课程列表", callback=self.refresh_courses))

        fetched_at = load_courses().get("fetched_at", "")
        if fetched_at:
            try:
                dt = datetime.fromisoformat(fetched_at)
                courses_menu.add(rumps.MenuItem(f"  上次刷新: {dt.strftime('%m-%d %H:%M')}", callback=None))
            except:
                pass

        courses_menu.add(rumps.separator)

        if enriched:
            for i, c in enumerate(enriched):
                name = c["name"]
                prog = c["progress_pct"]

                # 进度标记
                if prog >= 100:
                    icon = "✅"
                elif prog > 0:
                    icon = "📖"
                else:
                    icon = "📁"

                # 构建详情
                parts = []
                if prog > 0:
                    parts.append(f"{prog}%")
                if c["watched_lec"] > 0:
                    skipped = f" (含{c['skipped_lec']}跳)" if c["skipped_lec"] else ""
                    parts.append(f"刷{c['watched_lec']}节{skipped}")
                dur_str = _fmt_dur(c["watched_dur"])
                if c["watched_dur"] > 0:
                    parts.append(dur_str)

                # 总时长
                if c["total_hrs"]:
                    parts.append(f"共{c['total_hrs']}h")

                # 剩余
                remaining_parts = []
                if c["remaining_lec"]:
                    remaining_parts.append(f"剩{c['remaining_lec']}节")
                if c["remaining_time"]:
                    remaining_parts.append(_fmt_dur(c["remaining_time"]))
                if remaining_parts:
                    parts.append(f"({', '.join(remaining_parts)})")

                label = f"{i+1}. {icon} {name[:32]}"
                detail = " | ".join(parts) if parts else "未开始"
                detail_label = f"   {detail}"

                item = rumps.MenuItem(label)
                item.add(rumps.MenuItem(detail_label, callback=None))
                if c["url"]:
                    item.add(rumps.MenuItem("▶ 继续刷这门课", callback=self.select_course(c)))
                courses_menu.add(item)
        else:
            courses_menu.add(rumps.MenuItem("  (暂无课程，点击刷新获取)", callback=None))
        self.menu.add(courses_menu)

        self.menu.add(rumps.separator)

        # ── 总计与月度明细 ──
        total_item = rumps.MenuItem(f"总计 {tt:.1f}h")
        breakdown = monthly_breakdown(entries)
        if breakdown:
            for month, hours in breakdown.items():
                pct_str = ""
                if month == datetime.now().strftime("%Y-%m") and tg > 0:
                    pct_str = f" ({hours/tg*100:.0f}%)"
                total_item.add(rumps.MenuItem(f"  {month}: {hours:.1f}h{pct_str}", callback=None))
        else:
            total_item.add(rumps.MenuItem("  (暂无数据)", callback=None))
        self.menu.add(total_item)

        self.menu.add(rumps.separator)

        # ── 目标设置 ──
        target_menu = rumps.MenuItem("设置本月目标")
        for h in [10, 20, 30, 40, 50, 60]:
            mark = " ✓" if h == tg else ""
            target_menu.add(rumps.MenuItem(f"  {h}h{mark}", callback=self.set_target))
        self.menu.add(target_menu)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("退出", callback=self.quit_app))

    def refresh_courses(self, sender):
        rumps.notification("Udemy", "正在刷新课程列表...", "请等待浏览器窗口加载")
        try:
            subprocess.Popen(["/usr/bin/python3", FETCH_SCRIPT])
        except Exception as e:
            rumps.alert("刷新失败", str(e))

    def select_course(self, course):
        def cb(sender):
            url = course.get("url", "")
            if not url:
                rumps.alert("错误", "课程 URL 为空")
                return
            self._start_watch_with_url(url)
        return cb

    def resume_course(self, course_url):
        def cb(sender):
            self._start_watch_with_url(course_url)
        return cb

    def _start_watch_with_url(self, url):
        if self._watch_proc and self._watch_proc.poll() is None:
            self.stop_watch(None)
        target = load_target()
        self._watch_proc = subprocess.Popen(
            ["/usr/bin/python3", WATCH_SCRIPT, "--hours", str(target), "--rate", "2.0", "--resume", url]
        )
        self._build_menu()

    def start_watch(self, sender):
        if self._watch_proc and self._watch_proc.poll() is None: return
        target = load_target()
        self._watch_proc = subprocess.Popen(
            ["/usr/bin/python3", WATCH_SCRIPT, "--hours", str(target), "--rate", "2.0"]
        )
        self._build_menu()

    def stop_watch(self, sender):
        if self._watch_proc:
            self._watch_proc.terminate()
            self._watch_proc = None
        self._build_menu()

    def set_target(self, sender):
        try:
            h = int(sender.title.strip().replace("h", "").replace("✓", "").strip())
            save_target(h)
            self._build_menu()
        except ValueError:
            pass

    def quit_app(self, sender):
        if self._watch_proc:
            self._watch_proc.terminate()
        rumps.quit_application()

    @rumps.timer(10)
    def refresh(self, _):
        self._build_menu()


def main():
    """主入口函数，可被 .app launcher 或直接运行调用"""
    global DEBUG_LOG
    # 清空旧日志
    with open(DEBUG_LOG, "w") as f:
        f.write(f"[{datetime.now().isoformat()}] === UdemyBar 启动 ===\n")
    _debug(f"Python: {sys.executable}")
    _debug(f"Script dir: {SCRIPT_DIR}")
    _debug(f"rumps imported OK")
    _debug("创建 NSApplication...")
    app = NSApplication.sharedApplication()
    # 不再设置 accessory 模式 — 让 app 在 Dock 显示图标
    app.activateIgnoringOtherApps_(True)
    _debug("创建 UdemyBarApp...")
    udemy_app = UdemyBarApp()
    _debug("调用 .run()...")
    udemy_app.run()


if __name__ == "__main__":
    main()
