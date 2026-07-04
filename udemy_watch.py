#!/usr/bin/env python3
"""
Udemy 网课自动播放 — 精简版
支持断点续播、课程进度追踪
"""

import asyncio, json, os, random, time, argparse, traceback, re
from datetime import datetime

try:
    from playwright.async_api import async_playwright
except ImportError:
    import subprocess
    subprocess.run(["pip3", "install", "playwright"])
    subprocess.run(["python3", "-m", "playwright", "install", "chromium"])
    from playwright.async_api import async_playwright

# ── 配置 ──
COURSE_URL = "https://hta.udemy.com/organization/home/courses/  # 替换为你的 Udemy 课程 URL"
PROFILE = os.path.expanduser("~/Library/Application Support/Codex-Udemy-Chrome")
LOG = os.path.expanduser("~/udemy_watch_log.jsonl")
STATE_FILE = os.path.expanduser("~/udemy_watch_state.json")
COURSES_FILE = os.path.expanduser("~/udemy_courses.json")  # 课程元信息

def rd(min_s=0.3, max_s=1.5):
    time.sleep(random.uniform(min_s, max_s))

def monthly_h():
    if not os.path.exists(LOG): return 0
    ms = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    t = 0
    for l in open(LOG):
        try:
            e = json.loads(l.strip())
            if datetime.fromisoformat(e["ts"]) >= ms and e["status"] == "done":
                t += e["dur"]
        except: pass
    return t / 3600

def log_ev(title, dur, url="", course_name="", course_url=""):
    entry = {
        "ts": datetime.now().isoformat(),
        "title": title,
        "dur": dur,
        "status": "done",
        "course_name": course_name,
        "course_url": course_url,
    }
    with open(LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if url:
        save_state(url)


def log_skip(title, course_name="", course_url="", dur=300, url=""):
    """记录被标记完成但跳过的章节，使用估算时长（默认 5 分钟）。
    确保这些章节也被计入统计，避免总时长偏少。"""
    entry = {
        "ts": datetime.now().isoformat(),
        "title": title,
        "dur": dur,
        "status": "done",
        "skip": True,
        "course_name": course_name,
        "course_url": course_url,
    }
    with open(LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if url:
        save_state(url)


def _log_skip_with_info(log_info, url=""):
    """根据 try_skip 提供的上下文记录一条 done 日志。
    估算时长策略：优先用已传入的 dur，其次 5 分钟默认值。"""
    title = log_info.get("title", "N/A")
    cname = log_info.get("course_name", "")
    curl = log_info.get("course_url", "")
    dur = log_info.get("dur", 300)
    log_skip(title, cname, curl, dur, url)


def log_action(action, url="", detail="", success=True):
    """记录标记完成/跳过/导航等操作到日志文件。"""
    entry = {
        "ts": datetime.now().isoformat(),
        "action": action,
        "url": url,
        "detail": detail,
        "success": success,
        "status": "action",
    }
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except:
        pass

def save_state(url):
    json.dump({"last_url": url, "ts": datetime.now().isoformat()}, open(STATE_FILE, "w"))

def load_state():
    if os.path.exists(STATE_FILE):
        try: return json.load(open(STATE_FILE))
        except: pass
    return None

def save_course(course_name, course_url):
    """保存课程信息"""
    courses = {}
    if os.path.exists(COURSES_FILE):
        try: courses = json.load(open(COURSES_FILE))
        except: pass
    courses[course_name] = {
        "url": course_url,
        "name": course_name,
        "ts": datetime.now().isoformat(),
    }
    json.dump(courses, open(COURSES_FILE, "w"), ensure_ascii=False)

# ── 浏览器 ──
async def find_click_visible(page, selectors):
    for sel in selectors:
        els = await page.query_selector_all(sel)
        for el in els:
            try:
                if await el.is_visible():
                    await el.click(force=True, timeout=5000)
                    rd(1, 3)
                    return True
            except: continue
    return False

async def find_video(page):
    """在主文档和所有 iframe 中搜索 video 元素。
    返回 (element, frame) 元组；找不到返回 (None, None)。
    """
    # 先搜主文档
    vid = await page.query_selector("video")
    if vid:
        return (vid, page.main_frame)
    # 递归搜索 iframe
    for f in page.frames:
        if f == page.main_frame:
            continue
        vid = await f.query_selector("video")
        if vid:
            return (vid, f)
    return (None, None)

async def debug_dump_page(page, label=""):
    """当卡住时 dump 页面信息，用于诊断"""
    try:
        url = page.url
        print(f"  🔍 [{label}] URL: {url}")
        # 检查所有关键元素
        checks = {
            'video': 'video',
            'checkbox_input': 'input[data-purpose="progress-toggle-button"]',
            'checkbox_any': '[data-purpose="progress-toggle-button"]',
            'checkbox_button': 'button[data-purpose="progress-toggle-button"]',
            'next_go': '[data-purpose="go-to-next"]',
            'next_btn': '[data-purpose="next-button"]',
            'next_e2e': 'button[data-e2e="next-button"]',
            'curriculum_item': '[data-purpose="curriculum-item"]',
            'curriculum_item_link': '[data-purpose="curriculum-item-link"]',
            'lecture_title': '[data-purpose="lecture-title"]',
            'any_button_next': 'button:has-text("Next")',
            'any_button_complete': 'button:has-text("Mark")',
        }
        for name, sel in checks.items():
            els = await page.query_selector_all(sel)
            if els:
                print(f"  🔍 [{name}] {sel} → {len(els)} 个")
                for i, el in enumerate(els[:2]):
                    try:
                        vis = await el.is_visible()
                        txt = (await el.inner_text())[:60].strip() if vis else "(hidden)"
                        print(f"       [{i}] visible={vis} text={txt}")
                    except:
                        print(f"       [{i}] (read error)")
        # iframe 检查
        for i, frame in enumerate(page.frames):
            if frame == page.main_frame: continue
            try:
                vids = await frame.query_selector_all('video')
                if vids:
                    print(f"  🔍 iframe[{i}] 有 {len(vids)} 个 video")
            except: pass
        # 保存截图和 HTML
        await page.screenshot(path=os.path.expanduser("~/udemy_debug.png"))
        html = await page.content()
        with open(os.path.expanduser("~/udemy_debug.html"), "w") as f:
            f.write(html)
        print(f"  🔍 截图: ~/udemy_debug.png | HTML: ~/udemy_debug.html")
    except Exception as e:
        print(f"  🔍 dump 失败: {e}")


async def mark_as_complete(page):
    """在页面上下文中直接执行 JS 标记当前章节完成。
    修复：使用 dispatchEvent 代替 .click() 以兼容 React 元素。
    匹配中文和英文文本。"""
    result = await page.evaluate("""
        () => {
            function reactClick(el) {
                if (!el) return false;
                el.scrollIntoView({block: 'center', behavior: 'smooth'});
                el.dispatchEvent(new MouseEvent('click', {
                    bubbles: true, cancelable: true, view: window
                }));
                return true;
            }
            const log = [];

            // 方法1: 主内容区的 "标记为完成" 按钮 (action-button)
            const actionBtn = document.querySelector('button[data-purpose="action-button"]');
            if (actionBtn) {
                const txt = (actionBtn.textContent || '').trim().toLowerCase();
                log.push('action-button text: ' + txt);
                // 中文 "标记为完成" = 未完成；"已标记为完成" = 已完成
                if (txt.includes('标记为完成') && !txt.includes('已标记为完成')) {
                    reactClick(actionBtn);
                    log.push('CLICKED action-button (标记为完成)');
                    return {success: true, method: 'action-button', log: log};
                }
                if (txt.includes('mark as complete') && !txt.includes('mark as incomplete')) {
                    reactClick(actionBtn);
                    log.push('CLICKED action-button (Mark as complete)');
                    return {success: true, method: 'action-button-en', log: log};
                }
                // 如果已经是 "已标记为完成" / "Mark as incomplete"，跳过
                if (txt.includes('已标记为完成') || txt.includes('mark as incomplete')) {
                    log.push('action-button already marked: ' + txt);
                    return {success: true, method: 'already-marked', log: log};
                }
            }

            // 方法2: 通过 aria-label 找未完成的复选框 (中英文)
            const boxes = document.querySelectorAll('input[data-purpose="progress-toggle-button"]');
            log.push('checkbox count: ' + boxes.length);
            for (const box of boxes) {
                const label = (box.getAttribute('aria-label') || '').toLowerCase();
                log.push('box label: ' + label);
                // 英文："Mark as complete" = 未完成；"Mark as incomplete" = 已完成
                if (label.includes('mark as complete') && !label.includes('mark as incomplete')) {
                    reactClick(box);
                    log.push('CLICKED checkbox (en)');
                    return {success: true, method: 'checkbox-en', log: log};
                }
                // 中文："标记为已完成" (action text) + checked=false 表示未完成
                if (label.includes('标记为完成') && !box.checked) {
                    reactClick(box);
                    log.push('CLICKED checkbox (zh)');
                    return {success: true, method: 'checkbox-zh', log: log};
                }
            }

            // 方法3: 找所有未勾选的 checkbox（兜底）
            for (const box of boxes) {
                if (!box.checked) {
                    reactClick(box);
                    log.push('CLICKED unchecked box (fallback)');
                    return {success: true, method: 'unchecked-fallback', log: log};
                }
            }

            log.push('all boxes already checked or none found');
            return {success: false, method: 'none', log: log};
        }
    """)

    if result.get('success'):
        print(f"  ✓ 已标记完成 (method={result['method']})")
        log_action("mark_complete", page.url, f"method={result['method']}", True)
        for entry in result.get('log', []):
            if 'CLICKED' in entry or 'action-button' in entry:
                print(f"    → {entry}")
    else:
        print(f"  ⚠ mark_as_complete 失败: {result.get('log', [])}")
        log_action("mark_complete", page.url, f"failed: {result.get('log', [])}", False)
    return result.get('success', False)


async def click_next(page):
    """在页面上下文中直接执行 JS 点击 Next 按钮。
    修复：使用 dispatchEvent 代替 .click() 以兼容 React DIV 元素。"""
    result = await page.evaluate("""
        () => {
            function reactClick(el) {
                if (!el) return false;
                el.scrollIntoView({block: 'center', behavior: 'smooth'});
                el.dispatchEvent(new MouseEvent('click', {
                    bubbles: true, cancelable: true, view: window
                }));
                return true;
            }
            const selectors = [
                '[data-purpose="go-to-next"]',
                '[data-purpose="next-button"]',
                'button[data-e2e="next-button"]',
                '[aria-label="Next lecture"]',
                '[aria-label="Next"]',
                'button[aria-label="Next"]',
                '.next-button',
                '.curriculum-item-link--next',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    reactClick(el);
                    return {success: true, selector: sel};
                }
            }
            // 文本匹配 (中英文)
            const btns = document.querySelectorAll('button, a, [role="button"]');
            for (const btn of btns) {
                const txt = (btn.textContent || '').trim().toLowerCase();
                if (txt === 'next' || txt === 'next lecture' ||
                    txt === '下一节' || txt === '下一个' ||
                    txt.includes('next') || txt.includes('下一')) {
                    reactClick(btn);
                    return {success: true, selector: 'text:' + txt};
                }
            }
            return {success: false, selector: 'none'};
        }
    """)
    if result.get('success'):
        print(f"  ✓ 已点击 Next (selector={result['selector']})")
        log_action("click_next", page.url, f"selector={result['selector']}", True)
        return True
    else:
        # 兜底: 键盘快捷键
        try:
            await page.keyboard.press("n")
            print("  → 键盘 'n' 触发")
            log_action("click_next", page.url, "keyboard 'n'", True)
            return True
        except:
            print("  ⚠ click_next: 所有方法均失败")
            log_action("click_next", page.url, "all methods failed", False)
            return False

async def login_wait(page):
    print("  等登录...", end="", flush=True)
    while True:
        u = page.url.lower()
        if not any(k in u for k in ["login", "auth", "sso", "signin", "?next="]):
            if u.rstrip("/") not in ["https://hta.udemy.com", "https://hta.udemy.com/"]:
                ins = await page.query_selector_all('input[type="email"], input[type="password"]')
                if len(ins) < 2:
                    print(" ✓")
                    return
        await asyncio.sleep(3)

async def extract_course_info(page):
    """从页面提取课程名和课程 URL。
    多策略匹配，兼容 Udemy Business (HTA) 中文页面。"""
    course_name = ""
    course_url = ""
    try:
        # 策略1: 侧边栏课程标题
        name_selectors = [
            '[data-purpose="course-title"]',
            'a[data-purpose="course-title-url"]',
            '.udemy-breadcrumb a',
            '.course-title',
            'h1[data-purpose="course-header-title"]',
            '.section--course-title',
            'nav a[href*="/course/"]',
        ]
        for sel in name_selectors:
            els = await page.query_selector_all(sel)
            for el in els:
                try:
                    txt = (await el.inner_text()).strip()
                    if txt and len(txt) > 3 and not txt.startswith("http"):
                        # 过滤无关文本
                        if txt.lower() not in ("udemy business", "udemy", "我的学习", "my learning", "back"):
                            course_name = txt
                            break
                except:
                    continue
            if course_name:
                break

        # 策略2: 页面 title: "Lecture | Course Name | Udemy" 或 "章节名 | 课程名 | Udemy"
        if not course_name:
            t = await page.title()
            parts = t.split("|")
            if len(parts) >= 2:
                fn = parts[1].strip()
                if fn and fn.lower() not in ("udemy", "udemy business", "lecture"):
                    course_name = fn
            elif len(parts) == 1 and "-" in t:
                # "课程名 - Udemy" 格式
                fn = t.split("-")[0].strip()
                if len(fn) > 3:
                    course_name = fn

        # 提取课程 URL
        for sel in [
            'a[data-purpose="course-title-url"]',
            'a[href*="/course/"][href*="/learn/"]',
            'nav a[href*="/course/"]',
            '.breadcrumb a[href*="/course/"]',
        ]:
            if course_url:
                break
            els = await page.query_selector_all(sel)
            for el in els:
                href = (await el.get_attribute("href")) or ""
                m = re.search(r'/course/(\d+)', href)
                if m:
                    course_url = f"https://hta.udemy.com/course/{m.group(1)}/"
                    break
    except:
        pass
    return course_name, course_url

async def one_time_nav(page):
    for attempt in range(10):
        vid, _ = await find_video(page)
        if vid:
            return True
        
        u = page.url
        
        if "/learn/" in u:
            await click_next(page)
            rd(3, 6)
            continue
        
        if "/home/courses/" in u or "/organization/home/" in u:
            links = await page.query_selector_all('a[href*="/course/"]')
            for l in links:
                h = await l.get_attribute("href") or ""
                if h.startswith("/course/"):
                    print(f"  进入课程: {(await l.inner_text()).strip()[:50]}")
                    await page.goto(f"https://hta.udemy.com{h}", wait_until="domcontentloaded")
                    rd(4, 8)
                    break
            continue
        
        if "/course/" in u and "/learn/" not in u:
            if attempt < 2:
                await find_click_visible(page, [
                    'button:has-text("立即注册")',
                    '[data-purpose="buy-this-course-button"]',
                ])
                rd(3, 6)
            await find_click_visible(page, [
                'a:has-text("开始学习")',
                'a:has-text("Start")',
                'a:has-text("Go to course")',
                'a[href*="/learn/"]',
            ])
            rd(4, 8)
            continue
        
        rd(2, 4)
    return False


async def detect_video_error(page):
    """检测 Udemy 视频播放错误提示。
    页面可能出现 "视频错误" 或 "Video Error" 及相关描述文本。
    返回 True 表示检测到错误。"""
    try:
        result = await page.evaluate("""
            () => {
                const bodyText = document.body ? document.body.innerText : '';
                // 中文错误提示
                const zhPatterns = [
                    '视频错误',
                    '我们已经数次尝试播放您的视频',
                    '发生了未知错误',
                ];
                // 英文错误提示
                const enPatterns = [
                    'Video Error',
                    "We've tried playing your video several times",
                    'unknown error',
                    'Something went wrong',
                    'Error loading video',
                ];
                for (const p of zhPatterns) {
                    if (bodyText.includes(p)) return {error: true, lang: 'zh', match: p};
                }
                for (const p of enPatterns) {
                    if (bodyText.includes(p)) return {error: true, lang: 'en', match: p};
                }
                return {error: false};
            }
        """)
        return result
    except:
        return {"error": False}


async def reload_page(page):
    print("  🔄 刷新页面...")
    try:
        await page.reload(wait_until="domcontentloaded")
        rd(2, 4)
        for _ in range(20):
            vid, frame = await find_video(page)
            if vid:
                if await vid.evaluate("el => el.paused"):
                    await vid.evaluate("el => el.play()")
                print("  ✓ 视频已恢复")
                return True
            await asyncio.sleep(1)
        print("  ⚠ 刷新后仍无视频")
    except Exception as e:
        print(f"  ⚠ 刷新失败: {e}")
    return False


async def force_navigate_next(page, url_before):
    """终极手段：从侧边栏提取下一个 lecture 的 URL，直接 page.goto() 过去。
    所有 click 方式都失败时使用。"""
    try:
        next_url = await page.evaluate("""
            () => {
                const currentUrl = window.location.href;
                const currentLecture = currentUrl.match(/\/lecture\/(\d+)/);
                if (!currentLecture) return null;
                const currentId = currentLecture[1];

                // 方法1: 找侧边栏所有 lecture 链接，找当前的，返回下一个的 href
                const links = document.querySelectorAll('a[href*="/learn/lecture/"]');
                let found = false;
                for (const link of links) {
                    const href = link.getAttribute('href') || '';
                    const match = href.match(/\/lecture\/(\d+)/);
                    if (found && match) {
                        return link.href;  // 完整 URL
                    }
                    if (match && match[1] === currentId) {
                        found = true;
                    }
                }

                // 方法2: 找所有 curriculum-item div 里的链接
                const items = document.querySelectorAll('[data-purpose^="curriculum-item-"]');
                let foundCurrent = false;
                for (const item of items) {
                    if (foundCurrent) {
                        const link = item.querySelector('a[href*="/learn/lecture/"]');
                        if (link) return link.href;
                    }
                    const link = item.querySelector('a[href*="/learn/lecture/"]');
                    if (link) {
                        const match = (link.getAttribute('href') || '').match(/\/lecture\/(\d+)/);
                        if (match && match[1] === currentId) {
                            foundCurrent = true;
                        }
                    }
                }

                // 方法3: 收集所有 lecture ID，找当前 ID 的下一个
                const allLinks = Array.from(document.querySelectorAll('a[href*="/learn/lecture/"]'));
                const allIds = [];
                for (const l of allLinks) {
                    const m = (l.getAttribute('href') || '').match(/\/lecture\/(\d+)/);
                    if (m && !allIds.includes(m[1])) allIds.push(m[1]);
                }
                const idx = allIds.indexOf(currentId);
                if (idx >= 0 && idx < allIds.length - 1) {
                    // 构建完整 URL
                    const basePath = window.location.href.split('/lecture/')[0];
                    return basePath + '/lecture/' + allIds[idx + 1] + '/learning';
                }

                return null;
            }
        """)

        if next_url:
            print(f'  🔧 强制导航到: {next_url[:80]}...')
            log_action('force_navigate', url_before, f'next_url={next_url}', True)
            await page.goto(next_url, wait_until='domcontentloaded')
            await asyncio.sleep(3)
            if page.url != url_before:
                print(f'  ✓ 强制导航成功')
                return True
            else:
                print(f'  ⚠ 强制导航后 URL 未变化')
                log_action('force_navigate', url_before, 'URL unchanged after goto', False)
        else:
            print(f'  ⚠ 无法从侧边栏提取下一个 lecture URL')
            log_action('force_navigate', url_before, 'no next URL found in sidebar', False)
    except Exception as e:
        print(f'  ⚠ 强制导航失败: {e}')
        log_action('force_navigate', url_before, f'exception: {e}', False)
    return False


async def try_skip(page, last_url, label='', log_info=None):
    """统一的跳过逻辑：标记完成 → 点 Next → 验证跳转。
    返回 True 表示 URL 已变化（成功跳转），False 表示卡住。
    
    如果提供 log_info dict，成功时会自动记录到 log（避免统计遗漏）。
    log_info 应包含: title, course_name, course_url (均为可选)"""
    url_before = page.url
    print(f'  ⏭ [{label}] 开始跳过流程 (URL: {url_before[-50:]})')
    log_action('try_skip_start', url_before, f'label={label}', True)

    # Step 1: 标记完成
    await mark_as_complete(page)
    rd(1, 2)

    # Step 2: 点击 Next
    await click_next(page)
    rd(2, 4)

    # 等 JS 跳转生效
    await asyncio.sleep(2)
    url_after = page.url
    if url_after != url_before:
        print(f'  ✓ [{label}] 跳转成功 (click_next)')
        log_action('try_skip_success', url_before, f'method=click_next, url_after={url_after}', True)
        if log_info:
            _log_skip_with_info(log_info, page.url)
        return True

    # Step 3: 键盘兜底
    print(f'  → [{label}] click_next 未跳转，尝试键盘 n...')
    try:
        await page.keyboard.press('n')
        await asyncio.sleep(2)
    except:
        pass
    if page.url != url_before:
        print(f'  ✓ [{label}] 跳转成功 (keyboard n)')
        log_action('try_skip_success', url_before, 'method=keyboard_n', True)
        if log_info:
            _log_skip_with_info(log_info, page.url)
        return True

    # Step 4: 侧边栏点击下一个 lecture
    print(f'  → [{label}] 键盘未跳转，尝试侧边栏点击...')
    try:
        clicked = await page.evaluate("""
            () => {
                function reactClick(el) {
                    if (!el) return false;
                    el.scrollIntoView({block: 'center'});
                    el.dispatchEvent(new MouseEvent('click', {
                        bubbles: true, cancelable: true, view: window
                    }));
                    return true;
                }
                // 方法A: 找 curriculum-item-link 或 a[href*="/learn/lecture/"]
                const items1 = document.querySelectorAll('[data-purpose="curriculum-item-link"], a[href*="/learn/lecture/"]');
                let found_current = false;
                for (const item of items1) {
                    if (found_current) {
                        reactClick(item);
                        return {done: true, method: 'sidebar-link-next'};
                    }
                    if (item.getAttribute('aria-current') === 'true' ||
                        item.classList.contains('item-link--active') ||
                        item.parentElement?.classList.contains('active')) {
                        found_current = true;
                    }
                }
                // 方法B: 找所有 data-purpose="curriculum-item-X-Y" 的 div
                const items2 = document.querySelectorAll('[data-purpose^="curriculum-item-"]');
                let passed_current = false;
                for (let i = 0; i < items2.length; i++) {
                    const item = items2[i];
                    const cb = item.querySelector('input[data-purpose="progress-toggle-button"]');
                    if (passed_current && item) {
                        reactClick(item);
                        return {done: true, method: 'sidebar-div-next'};
                    }
                    if (cb && !cb.checked) {
                        passed_current = true;
                    }
                }
                // 方法C: sibling
                for (const item of items2) {
                    const cb = item.querySelector('input[data-purpose="progress-toggle-button"]');
                    if (cb && !cb.checked) {
                        let next = item.nextElementSibling;
                        while (next && !next.querySelector('input[data-purpose="progress-toggle-button"]')) {
                            next = next.nextElementSibling;
                        }
                        if (next) {
                            reactClick(next);
                            return {done: true, method: 'sidebar-div-sibling'};
                        }
                        break;
                    }
                }
                return {done: false};
            }
        """)
        if clicked and clicked.get('done'):
            await asyncio.sleep(3)
            if page.url != url_before:
                print(f'  ✓ [{label}] 跳转成功 ({clicked.get("method", "sidebar")})')
                log_action('try_skip_success', url_before, f'method={clicked.get("method")}', True)
                if log_info:
                    _log_skip_with_info(log_info, page.url)
                return True
    except:
        pass

    # Step 5: 终极手段 — 直接 page.goto() 下一个 lecture URL
    print(f'  → [{label}] 所有 click 方式失败，尝试强制导航...')
    if await force_navigate_next(page, url_before):
        log_action('try_skip_success', url_before, 'method=force_navigate', True)
        if log_info:
            _log_skip_with_info(log_info, page.url)
        return True

    # 全部失败 → dump
    print(f'  ⚠ [{label}] 所有跳过方法失败（包括强制导航）！')
    log_action('try_skip_fail', url_before, f'label={label}, all methods failed including force_navigate', False)
    await debug_dump_page(page, label)
    return False


async def watch(page, target_s, rate):
    start = time.time()
    title = "N/A"
    course_name = ""
    course_url = ""
    vid_read_fail = 0
    no_vid = 0
    last_progress = time.time()
    last_ct = -1
    stag_count = 0       # currentTime 连续停滞次数
    refresh_count = 0    # 同一章节连续刷新次数
    play_fail = 0        # 连续调用 play() 但视频仍暂停的次数
    error_retry_count = 0  # 视频错误重试次数（同一章节）
    MAX_ERROR_RETRIES = 3  # 最多刷新重试 3 次，超过则标记完成跳过
    last_url = page.url

    # 提取课程信息
    cname, curl = await extract_course_info(page)
    if cname:
        course_name = cname
        course_url = curl
        if course_name and course_url:
            save_course(course_name, course_url)
            print(f"  📚 课程: {course_name}")

    print(f"\n  ▶ 播放 ({rate}x)")
    while target_s <= 0 or (time.time() - start) < target_s:
        # ── 检测页面切换（URL 变化）→ 重置卡顿计时 ──
        cur_url = page.url
        if cur_url != last_url:
            last_url = cur_url
            last_progress = time.time()
            last_ct = -1
            no_vid = 0
            stag_count = 0
            refresh_count = 0
            vid_read_fail = 0
            play_fail = 0
            error_retry_count = 0

        try:
            for sel in ['[data-purpose="lecture-title"]', 'h1']:
                el = await page.query_selector(sel)
                if el:
                    t = (await el.inner_text()).strip()
                    if t and t != title:
                        title = t
                        print(f"  ▶ {title[:60]}")
                        save_state(page.url)
                        # 重新提取课程信息（切换课程时）
                        cname, curl = await extract_course_info(page)
                        if cname:
                            course_name = cname
                        if curl:
                            course_url = curl
                        if course_name and course_url:
                            save_course(course_name, course_url)
                    break
        except: pass

        # ── 视频错误检测 ──
        # Udemy 偶发 "视频错误/Video Error" 提示，检测到后自动刷新重试
        err_check = await detect_video_error(page)
        if err_check.get("error"):
            error_retry_count += 1
            match_text = err_check.get("match", "")
            lang = err_check.get("lang", "")
            print(f"  ⚠ 检测到视频错误 ({lang}: {match_text}) 第 {error_retry_count}/{MAX_ERROR_RETRIES} 次")
            log_action("video_error_detected", page.url, f"match={match_text}, lang={lang}, retry={error_retry_count}", False)

            if error_retry_count >= MAX_ERROR_RETRIES:
                print(f"  ⏭ 视频错误已重试 {MAX_ERROR_RETRIES} 次仍失败，标记完成并跳过")
                log_action("video_error_give_up", page.url, f"max retries ({MAX_ERROR_RETRIES}) exceeded, skipping", False)
                error_retry_count = 0
                if await try_skip(page, last_url, "video-error",
                                   {"title": title, "course_name": course_name, "course_url": course_url}):
                    no_vid = 0; last_ct = -1; stag_count = 0
                    play_fail = 0; refresh_count = 0
                    last_progress = time.time()
                rd(1, 2)
                continue

            # 刷新页面并等待视频恢复
            print(f"  🔄 刷新页面重试...")
            try:
                await page.reload(wait_until="domcontentloaded")
                rd(3, 5)
                # 等待视频元素出现并尝试播放
                recovered = False
                for _ in range(20):
                    vid2, _ = await find_video(page)
                    if vid2:
                        # 确认错误提示已消失
                        err_after = await detect_video_error(page)
                        if not err_after.get("error"):
                            if await vid2.evaluate("el => el.paused"):
                                await vid2.evaluate("el => el.play()")
                            # 验证视频真的能播放
                            ct_before = await vid2.evaluate("el => el.currentTime")
                            await asyncio.sleep(2)
                            ct_after = await vid2.evaluate("el => el.currentTime")
                            if ct_after > ct_before + 0.1 or not await vid2.evaluate("el => el.paused"):
                                recovered = True
                                print(f"  ✓ 刷新后视频已恢复 (第 {error_retry_count} 次重试成功)")
                                log_action("video_error_recovered", page.url, f"retry={error_retry_count}", True)
                                break
                        else:
                            print(f"  ⚠ 刷新后仍有视频错误提示，继续等待...")
                    await asyncio.sleep(1)
                if recovered:
                    error_retry_count = 0
                    last_progress = time.time()
                    last_ct = -1
                    stag_count = 0
                    play_fail = 0
                else:
                    print(f"  ⚠ 刷新后视频未恢复，将再次重试")
                    log_action("video_error_retry_fail", page.url, f"retry={error_retry_count}, not recovered", False)
            except Exception as e:
                print(f"  ⚠ 刷新失败: {e}")
                log_action("video_error_refresh_fail", page.url, f"exception: {e}", False)
            rd(1, 2)
            continue

        # ── 跨 iframe 查找视频 ──
        vid, vframe = await find_video(page)
        if vid:
            try:
                dur = await vid.evaluate("el => el.duration")
                # 视频元素存在但无实际内容（duration 为 NaN/0/None）→ 标记完成+跳过
                if dur is None or (isinstance(dur, (int, float)) and (dur != dur or dur <= 0)):
                    no_vid += 1
                    if no_vid >= 2:
                        print(f"  ⏭ 无视频内容(duration={dur})，标记完成并跳过")
                        if await try_skip(page, last_url, "no-content",
                                           {"title": title, "course_name": course_name, "course_url": course_url}):
                            no_vid = 0; last_ct = -1; stag_count = 0
                            refresh_count = 0; play_fail = 0
                            last_progress = time.time()
                        else:
                            no_vid = 0  # 防止重复触发，但不重置 last_progress
                        rd(1, 2)
                        continue
                    await asyncio.sleep(2)
                    continue

                no_vid = 0
                paused = await vid.evaluate("el => el.paused")
                ct = await vid.evaluate("el => el.currentTime")
                if paused:
                    # ⚠ 关键修复：不再无条件重置 last_progress！
                    # 只有视频真正开始播放后才重置。否则 play_fail 累积。
                    await vid.evaluate("el => el.play()")
                    play_fail += 1
                    vid_read_fail = 0
                    if play_fail >= 3:
                        print(f"  ⏭ play() {play_fail}次仍暂停，标记完成跳过")
                        play_fail = 0
                        if await try_skip(page, last_url, "play-fail",
                                           {"title": title, "course_name": course_name, "course_url": course_url}):
                            last_ct = -1; stag_count = 0
                            last_progress = time.time()
                        rd(1, 2)
                        continue
                    # 注意：不重置 last_progress！让 stuck_dur 继续累积
                elif ct >= dur - 6:
                    print(f"  → 章节结束 ({ct:.0f}s)")
                    log_ev(title, dur, page.url, course_name, course_url)
                    await click_next(page)
                    last_progress = time.time()
                    last_ct = -1
                    play_fail = 0
                    error_retry_count = 0
                    rd(3, 6)
                    vid_read_fail = 0
                else:
                    await vid.evaluate(f"el => el.playbackRate = {rate}")
                    if ct > last_ct + 0.1:
                        # 视频真的在前进 → 重置所有计数器
                        last_ct = ct
                        last_progress = time.time()
                        stag_count = 0
                        play_fail = 0
                        error_retry_count = 0
                    else:
                        stag_count += 1
                        if stag_count >= 4:
                            print(f"  ⏭ currentTime 停滞 {stag_count}轮(ct={ct:.1f})，标记完成跳过")
                            stag_count = 0
                            if await try_skip(page, last_url, "stag",
                                               {"title": title, "course_name": course_name, "course_url": course_url}):
                                last_ct = -1; play_fail = 0
                                last_progress = time.time()
                            rd(1, 2)
                            continue
                    vid_read_fail = 0
            except Exception as e:
                # 视频元素不可访问 → 连续 3 次失败则标记完成+跳过
                vid_read_fail += 1
                if vid_read_fail >= 3:
                    print(f"  ⏭ 视频不可访问({e})，标记完成并跳过")
                    if await try_skip(page, last_url, "except",
                                       {"title": title, "course_name": course_name, "course_url": course_url}):
                        no_vid = 0; vid_read_fail = 0; last_ct = -1
                        stag_count = 0; refresh_count = 0; play_fail = 0
                        last_progress = time.time()
                    else:
                        vid_read_fail = 0
                    rd(1, 2)
                    continue
                await asyncio.sleep(2)
        else:
            no_vid += 1
            if no_vid >= 1:
                print(f"  ⏭ 无视频元素，标记完成并跳过")
                if await try_skip(page, last_url, "no-video",
                                   {"title": title, "course_name": course_name, "course_url": course_url}):
                    no_vid = 0; last_ct = -1; stag_count = 0
                    refresh_count = 0; play_fail = 0
                    last_progress = time.time()
                else:
                    no_vid = 0  # 不重置 last_progress，让 stuck_dur 继续累积
                rd(1, 2)
                continue

        # ── 卡顿检测：15s 无进展 → 刷新；30s → 标记完成跳过 ──
        stuck_dur = time.time() - last_progress
        if stuck_dur > 30:
            print(f"  ⏭ 卡住 {stuck_dur:.0f}s，标记完成强制跳过")
            if await try_skip(page, last_url, "stuck-30s",
                               {"title": title, "course_name": course_name, "course_url": course_url}):
                no_vid = 0; last_ct = -1; stag_count = 0
                play_fail = 0; refresh_count = 0
                last_progress = time.time()
            else:
                no_vid = 0; refresh_count = 0
            rd(1, 2)
        elif stuck_dur > 15:
            refresh_count += 1
            if refresh_count >= 2:
                print(f"  ⏭ 已刷新 {refresh_count}次仍卡住，标记完成跳过")
                if await try_skip(page, last_url, "stuck-refresh",
                                   {"title": title, "course_name": course_name, "course_url": course_url}):
                    no_vid = 0; last_ct = -1; stag_count = 0
                    play_fail = 0; refresh_count = 0
                    last_progress = time.time()
                else:
                    no_vid = 0; refresh_count = 0
                rd(1, 2)
            else:
                no_vid = 0
                last_ct = -1
                stag_count = 0
                print(f"  🔄 卡住 {stuck_dur:.0f}s，尝试刷新 ({refresh_count}/2)...")
                recovered = False
                try:
                    await page.reload(wait_until="domcontentloaded")
                    rd(2, 4)
                    for _ in range(15):
                        vid2, _ = await find_video(page)
                        if vid2:
                            if await vid2.evaluate("el => el.paused"):
                                await vid2.evaluate("el => el.play()")
                            # 验证视频真的在播放（currentTime 会前进）
                            ct2 = await vid2.evaluate("el => el.currentTime")
                            await asyncio.sleep(2)
                            ct3 = await vid2.evaluate("el => el.currentTime")
                            if ct3 > ct2 + 0.1:
                                recovered = True
                                print("  ✓ 刷新恢复，视频正在播放")
                                break
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"  ⚠ 刷新失败: {e}")
                if recovered:
                    last_progress = time.time()
                    refresh_count = 0
                # 注意：如果没恢复，last_progress 不重置，stuck_dur 会继续增长到 >30

        elapsed = time.time() - start
        if int(elapsed) % 60 < 3 and elapsed > 30:
            mh = monthly_h()
            print(f"  [{int(elapsed//60)}m | 本月 {mh:.1f}h]")

        rd(3, 6)

    elapsed = time.time() - start
    mh = monthly_h()
    print(f"\n  完成 {elapsed/60:.0f}m | 本月 {mh:.1f}h/30h")
    return elapsed

# ── 主流程 ──
async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=float, default=1)
    p.add_argument("--minutes", type=float, default=0)
    p.add_argument("--rate", type=float, default=1.0)
    p.add_argument("--summary", action="store_true")
    p.add_argument("--course", type=str, default=COURSE_URL)
    p.add_argument("--resume", type=str, default="")  # 指定续播课程 URL
    a = p.parse_args()

    rate = min(max(a.rate, 0.5), 2.0)
    target = int(a.hours * 3600 + a.minutes * 60)
    
    print("═══ Udemy 自动播放 ═══")
    if a.summary:
        print(f"  本月: {monthly_h():.1f}h/30h")
        return
    print(f"  本月: {monthly_h():.1f}h/30h | 目标: {target//3600}h{target%3600//60}m | {rate}x")

    async with async_playwright() as pw:
        print("  启动 Chrome...")
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE, headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            viewport=None, ignore_default_args=["--enable-automation"])
        page = browser.pages[0] if browser.pages else await browser.new_page()

        # ── 确定起始 URL ──
        start_url = a.course
        if a.resume:
            start_url = a.resume
            print(f"  📍 续播课程: {start_url[:80]}...")
        else:
            state = load_state()
            if state and state.get("last_url"):
                start_url = state["last_url"]
                print(f"  📍 断点续播: {start_url[:80]}...")
                print(f"     (上次: {state.get('ts', '')})")

        await page.goto(start_url, wait_until="domcontentloaded")
        rd(3, 6)
        await login_wait(page)
        
        vid, _ = await find_video(page)
        if vid:
            print("  ✓ 已定位到视频，直接播放")
        else:
            print("  导航中...")
            if not await one_time_nav(page):
                print("  请在浏览器中手动打开视频页面，脚本自动开始...")
                for _ in range(120):
                    vid, _ = await find_video(page)
                    if vid: break
                    await asyncio.sleep(3)

        try:
            await watch(page, target, rate)
        except KeyboardInterrupt:
            print("\n  手动停止")
        except Exception as e:
            print(f"  ✗ {e}")
            traceback.print_exc()

        mh = monthly_h()
        print(f"\n  本月累计: {mh:.1f}h/30h")
        print("  Enter 退出")
        try: input()
        except: pass
        await browser.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\n  退出")
