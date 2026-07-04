#!/usr/bin/env python3
"""
Udemy 刷课 - macOS 菜单栏
"""
import json, os, subprocess, sys
from datetime import datetime
import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def _find_icon(name):
    """优先从脚本目录查找图标，其次 ~/udemy_icons/"""
    p = os.path.join(SCRIPT_DIR, name)
    if os.path.exists(p):
        return p
    p2 = os.path.expanduser(f"~/udemy_icons/{name}")
    if os.path.exists(p2):
        return p2
    return None

ICON_PLAY = _find_icon("play.png")
ICON_STOP = _find_icon("stop.png")

WATCH_SCRIPT = os.path.join(SCRIPT_DIR, "udemy_watch.py")
FETCH_SCRIPT = os.path.join(SCRIPT_DIR, "fetch_courses.py")
LOG_FILE = os.path.expanduser("~/udemy_watch_log.jsonl")
TARGET_FILE = os.path.expanduser("~/udemy_target_hours.json")
COURSES_FILE = os.path.expanduser("~/udemy_courses.json")


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
            elif isinstance(data, dict):
                return {"courses": [], "fetched_at": "", "count": 0}
        except: pass
    return {"courses": [], "fetched_at": "", "count": 0}


def monthly_hours(entries):
    now = datetime.now()
    ms = datetime(now.year, now.month, 1)
    me = datetime(now.year + 1, 1, 1) if now.month == 12 else datetime(now.year, now.month + 1, 1)
    return sum(e["dur"] for e in entries if ms <= datetime.fromisoformat(e["ts"]) < me and e["status"] == "done") / 3600


def total_hours(entries):
    return sum(e["dur"] for e in entries if e["status"] == "done") / 3600


def course_stats(entries):
    """按课程统计：{course_name: {lecture_count, total_dur, course_url, last_ts}}"""
    stats = {}
    for e in entries:
        if e["status"] != "done": continue
        cn = e.get("course_name", "")
        cu = e.get("course_url", "")
        if not cn:
            cn = "(未分类)"
        if cn not in stats:
            stats[cn] = {"count": 0, "total_dur": 0, "url": cu, "last_ts": e["ts"]}
        stats[cn]["count"] += 1
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


class UdemyBarApp(rumps.App):
    def __init__(self):
        super(UdemyBarApp, self).__init__(
            "Udemy",
            title="Udemy",
            icon=ICON_PLAY,
            template=False,
            quit_button=None,
        )
        self._watch_proc = None
        self._build_menu()

    def _build_menu(self):
        self.menu.clear()
        entries = load_logs()
        stats = course_stats(entries)
        courses_data = load_courses()
        courses = courses_data.get("courses", [])
        tg = load_target()
        mn = monthly_hours(entries)
        tt = total_hours(entries)
        running = self._watch_proc is not None and self._watch_proc.poll() is None

        if running:
            self.title = "⏹ Udemy"
            self.icon = ICON_STOP
        else:
            self.title = "▶ Udemy"
            self.icon = ICON_PLAY

        # ── 开始/停止刷课 ──
        if running:
            self.menu.add(rumps.MenuItem("⏹ 停止刷课", callback=self.stop_watch))
            self.menu.add(rumps.MenuItem("● 运行中...", callback=None))
        else:
            self.menu.add(rumps.MenuItem("▶ 开始刷课", callback=self.start_watch))

        self.menu.add(rumps.separator)

        # ── 课程列表（可选择的） ──
        courses_menu = rumps.MenuItem("📚 课程列表")
        courses_menu.add(rumps.MenuItem("🔄 刷新课程列表", callback=self.refresh_courses))
        courses_menu.add(rumps.separator)
        if courses:
            for i, c in enumerate(courses):
                prog = f" [{c.get('progress', '')}%]" if c.get('progress') else ""
                name = c.get("name", "(未知名称)")
                label = f"{i+1}. {name[:35]}{prog}"
                item = rumps.MenuItem(label, callback=self.select_course(c))
                courses_menu.add(item)
        else:
            courses_menu.add(rumps.MenuItem("  (暂无课程，点击刷新)", callback=None))
        self.menu.add(courses_menu)

        self.menu.add(rumps.separator)

        # ── 已刷课程（含进度） ──
        self.menu.add(rumps.MenuItem("已刷课程", callback=None))
        if stats:
            for cname in sorted(stats.keys()):
                s = stats[cname]
                mins = int(s["total_dur"] / 60)
                curl = s.get("url", "")
                label = f"  {cname[:25]} ({s['count']}节, {mins}m)"
                item = rumps.MenuItem(label)
                item.add(rumps.MenuItem(f"已刷 {s['count']} 节 | 共 {mins}m", callback=None))
                if curl:
                    item.add(rumps.separator)
                    item.add(rumps.MenuItem("▶ 继续刷这门课", callback=self.resume_course(curl)))
                self.menu.add(item)
        else:
            self.menu.add(rumps.MenuItem("  (暂无记录)", callback=None))

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem(f"本月 {mn:.1f}h / {tg}h", callback=None))

        total_item = rumps.MenuItem(f"总计 {tt:.1f}h")
        breakdown = monthly_breakdown(entries)
        if breakdown:
            for month, hours in breakdown.items():
                total_item.add(rumps.MenuItem(f"{month}: {hours:.1f}h", callback=None))
        else:
            total_item.add(rumps.MenuItem("(暂无数据)", callback=None))
        self.menu.add(total_item)

        self.menu.add(rumps.separator)
        target_menu = rumps.MenuItem("设置本月目标")
        for h in [10, 20, 30, 40, 50, 60]:
            target_menu.add(rumps.MenuItem(f"{h}h", callback=self.set_target))
        self.menu.add(target_menu)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("退出", callback=self.quit_app))

    def refresh_courses(self, sender):
        """运行 fetch_courses.py 刷新课程列表"""
        rumps.notification("Udemy", "正在刷新课程列表...", "请等待浏览器窗口加载")
        try:
            subprocess.Popen(["/usr/bin/python3", FETCH_SCRIPT])
        except Exception as e:
            rumps.alert("刷新失败", str(e))

    def select_course(self, course):
        """返回一个 callback，点击后开始刷选中的课程"""
        def cb(sender):
            url = course.get("url", "")
            if not url:
                rumps.alert("错误", "课程 URL 为空")
                return
            self._start_watch_with_url(url)
        return cb

    def resume_course(self, course_url):
        """返回一个 callback，点击后启动续播"""
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
            h = int(sender.title.replace("h", ""))
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


if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    UdemyBarApp().run()
