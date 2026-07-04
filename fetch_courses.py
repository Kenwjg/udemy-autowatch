#!/usr/bin/env python3
"""
抓取 Udemy 已注册课程列表（增强版）。
1. 打开 "My Learning" 页面，提取所有课程名称、URL 和进度%。
2. 进入每门课程的学习页面，抓取总章节数和总时长。
3. 结果保存到 ~/udemy_courses.json
"""
import asyncio
import json
import os
import time
from datetime import datetime

from playwright.async_api import async_playwright

PROFILE = os.path.expanduser("~/Library/Application Support/Codex-Udemy-Chrome")
COURSES_FILE = os.path.expanduser("~/udemy_courses.json")

# Udemy Business 的 "我的学习" 页面
MY_LEARNING_URL = "https://hta.udemy.com/home/my-courses/learning/"


async def extract_courses_from_my_learning(page):
    """从 My Learning 页面提取课程基本信息（名称、URL、进度）"""
    print("  提取课程基本信息...")
    courses = await page.evaluate("""
        () => {
            const results = [];
            const seen = new Set();

            // 策略1: 以 course-dashboard-redirect 链接为锚点
            const dashboardLinks = document.querySelectorAll('a[href*="course-dashboard-redirect"]');

            dashboardLinks.forEach(link => {
                const href = (link.getAttribute('href') || '').trim();
                if (!href || seen.has(href)) return;
                if (href.includes('course_id=') && href.includes('course-dashboard-redirect')) {
                    seen.add(href);
                }

                let url = href;
                if (href.startsWith('/')) {
                    url = window.location.origin + href;
                }

                // 找课程名：从卡片/容器中取最长文本
                let name = (link.textContent || '').trim();

                // 往上找更完整的标题（h3 / card-title 等）
                let card = link.closest('[class*="card"]') || link.closest('[class*="course-card"]');
                if (!card) {
                    // 尝试找包含图片和标题的父容器
                    card = link.closest('div');
                    while (card && card !== document.body) {
                        const imgs = card.querySelectorAll('img');
                        const links = card.querySelectorAll('a[href*="course-dashboard-redirect"]');
                        if (imgs.length >= 1 && links.length <= 2) break; // 大概率是课程卡片
                        card = card.parentElement;
                    }
                }

                if (card) {
                    // 从卡片中找标题元素
                    const titleEls = card.querySelectorAll(
                        'h3, h2, [class*="title"], [class*="heading"], [data-purpose="course-title"]'
                    );
                    for (const el of titleEls) {
                        const txt = el.textContent.trim();
                        if (txt.length > name.length && txt.length > 3) {
                            name = txt;
                        }
                    }
                }

                // ── 进度提取（多策略） ──
                let progress = '';
                let lectures_completed = '';
                let lectures_total = '';
                let total_hours = '';

                const searchArea = card || document.body;

                // 策略A: progress / meter 元素
                const meters = searchArea.querySelectorAll(
                    'progress, meter, [role="progressbar"], [data-purpose="course-progress"]'
                );
                for (const m of meters) {
                    const val = m.getAttribute('value') || m.getAttribute('aria-valuenow');
                    if (val) { progress = val; break; }
                }

                // 策略B: 文本搜索 "X%" (中英文)
                if (!progress) {
                    const allText = searchArea.innerText || '';
                    const matchPct = allText.match(/(\d{1,3})\s*%(\s*(complete|完成|完了|complete))?/i);
                    if (matchPct) progress = matchPct[1];
                }

                // 策略C: 进度条宽度
                if (!progress) {
                    const bar = searchArea.querySelector('[class*="progress-bar"] div, [style*="width"]');
                    if (bar) {
                        const style = bar.getAttribute('style') || '';
                        const wm = style.match(/width:\s*(\d+)%?/);
                        if (wm) progress = wm[1];
                    }
                }

                // 策略D: aria-label
                if (!progress) {
                    const ariaProg = searchArea.querySelector('[aria-label*="%"]');
                    if (ariaProg) {
                        const al = ariaProg.getAttribute('aria-label') || '';
                        const m = al.match(/(\d+)\s*%/);
                        if (m) progress = m[1];
                    }
                }

                // ── 讲座数提取 ──
                const allText = searchArea.innerText || '';
                // 中文: "X / Y 节" / "X/Y 个讲座"
                let lcMatch = allText.match(/(\d+)\s*\/\s*(\d+)\s*(?:个)?\s*(?:节|讲座|lecture|lec|lectures?)/i);
                if (lcMatch) {
                    lectures_completed = lcMatch[1];
                    lectures_total = lcMatch[2];
                }
                // 英文: "X / Y lectures" / "X of Y complete"
                if (!lcMatch) {
                    lcMatch = allText.match(/(\d+)\s*(?:of|out of|\/)\s*(\d+)\s*(?:lectures?|complete)/i);
                    if (lcMatch) {
                        lectures_completed = lcMatch[1];
                        lectures_total = lcMatch[2];
                    }
                }

                // ── 总时长提取 ──
                const durMatch = allText.match(/(\d+[\.,]?\d*)\s*(?:hours?|h|小时|小時|hrs?)\s*(?:(\d+)\s*(?:minutes?|m|分钟|分鐘|mins?))?/i);
                if (durMatch) {
                    const h = parseFloat(durMatch[1].replace(',', '.')) || 0;
                    const m = parseInt(durMatch[2]) || 0;
                    total_hours = String(h + m / 60);
                }

                results.push({
                    name: name,
                    url: url,
                    progress: progress,
                    lectures_completed: lectures_completed,
                    lectures_total: lectures_total,
                    total_hours: total_hours,
                });
            });

            return results;
        }
    """)

    # 去重
    seen = set()
    unique = []
    for c in courses:
        key = c["url"]
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


async def fetch_course_metadata(page, course):
    """进入课程详情/学习页面，抓取总章节数和总时长"""
    url = course.get("url", "")
    if not url:
        return course

    # 如果卡片上已经拿到了足够数据，跳过
    if course.get("lectures_total") and course.get("total_hours"):
        return course

    try:
        # dashboard-redirect URL 会跳转到课程学习页面
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 等待页面加载
        for _ in range(10):
            loaded = await page.evaluate("""
                () => {
                    const skeletons = document.querySelectorAll('[class*="skeleton"]');
                    return skeletons.length === 0;
                }
            """)
            if loaded:
                break
            await asyncio.sleep(1)

        meta = await page.evaluate("""
            () => {
                let lectures_total = '';
                let total_hours = '';
                const bodyText = document.body ? document.body.innerText : '';

                // 找总章节数
                const sectionHeaders = document.querySelectorAll('[data-purpose="section-title"], .section-title, [class*="section-panel"]');
                const curriculumItems = document.querySelectorAll('[data-purpose^="curriculum-item-"]');
                if (curriculumItems.length > 0) {
                    lectures_total = String(curriculumItems.length);
                }

                // 如果侧边栏没有，在页面文本中搜索
                if (!lectures_total) {
                    // "X lectures" / "X 个讲座" / "X 节课"
                    let m = bodyText.match(/(\d+)\s*(?:lectures?|个?讲座|节(?:课|讲座)?|lec)/i);
                    if (m) lectures_total = m[1];
                }

                // 总时长
                let m = bodyText.match(/(\d+[\\.]?\d*)\s*(?:hours?|h|小时|小時|hrs?)\s*(?:(\d+)\s*(?:minutes?|m|分钟|分鐘|mins?))?\s*(?:total|on-demand|总|總)?/i);
                if (m) {
                    const h = parseFloat(m[1].replace(',', '.')) || 0;
                    const min = parseInt(m[2]) || 0;
                    total_hours = String(Math.round((h + min / 60) * 10) / 10);
                }

                // 与 "个讲座" 连在一起的时长
                if (!total_hours) {
                    m = bodyText.match(/(\d+)\s*(?:lectures?|个讲座|节)\s*[·•]?\s*(?:(\d+)\s*(?:total\s*)?hours?\s*(?:(\d+)\s*(?:total\s*)?mins?)?|(\d+)h\s*(?:(\d+)m)?|(\d+):(\d+))/i);
                    if (m) {
                        const h = parseInt(m[2] || m[4] || m[6] || '0') || 0;
                        const min = parseInt(m[3] || m[5] || m[7] || '0') || 0;
                        total_hours = String(Math.round((h + min / 60) * 10) / 10);
                    }
                }

                // 中文: "共X小时" / "共X分钟"
                if (!total_hours) {
                    m = bodyText.match(/(?:共|总|總)\s*(\d+)\s*(?:小时|小時|h|hr)/);
                    if (m) total_hours = m[1];
                    m = bodyText.match(/(?:共|总|總)\s*(\d+)\s*(?:分钟|分鐘|min)/);
                    if (m) total_hours = String(Math.round((parseInt(m[1]) / 60) * 10) / 10);
                }

                return { lectures_total, total_hours };
            }
        """)

        if meta.get("lectures_total"):
            course["lectures_total"] = meta["lectures_total"]
        if meta.get("total_hours"):
            course["total_hours"] = meta["total_hours"]

    except Exception as e:
        print(f"    ⚠ 获取 {course.get('name', '?')[:30]} 元数据失败: {e}")

    return course


async def fetch_courses():
    async with async_playwright() as pw:
        print("  启动 Chrome...")
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE,
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            viewport=None,
            ignore_default_args=["--enable-automation"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()

        print(f"  导航到 My Learning 页面...")
        await page.goto(MY_LEARNING_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 检查是否是需要登录的页面
        if "login" in page.url.lower() or "sign-in" in page.url.lower():
            print("  ⚠ 需要登录，请在浏览器中登录后按 Enter 继续...")
            input()

        # 等待 skeleton 消失（课程卡片加载完成）
        print("  等待课程卡片加载...")
        for _ in range(15):
            skeleton_count = await page.evaluate(
                """() => document.querySelectorAll('[data-purpose="course-card-skeleton"], [class*="skeleton"]').length"""
            )
            if skeleton_count == 0:
                print("  课程卡片加载完成")
                break
            await asyncio.sleep(1)
        else:
            print("  课程卡片仍在加载中，继续尝试...")

        # 滚动加载所有课程（Udemy 可能用懒加载）
        print("  滚动加载课程...")
        prev_count = 0
        for _ in range(20):
            count = await page.evaluate(
                """() => document.querySelectorAll('a[href*="course-dashboard-redirect"]').length"""
            )
            if count == prev_count and count > 0:
                print(f"  课程数量稳定: {count}")
                break
            prev_count = count
            await page.evaluate("window.scrollBy(0, 2000)")
            await asyncio.sleep(1)

        # ── 第1阶段: 提取基本信息 ──
        courses = await extract_courses_from_my_learning(page)

        print(f"\n  找到 {len(courses)} 门课程:\n")
        for i, c in enumerate(courses):
            prog = f" [{c.get('progress', '')}%]" if c.get('progress') else ""
            extra = []
            if c.get('lectures_total'): extra.append(f"{c['lectures_total']}节")
            if c.get('total_hours'): extra.append(f"{c['total_hours']}h")
            ext_str = f" ({', '.join(extra)})" if extra else ""
            print(f"    {i+1}. {c['name'][:50]}{prog}{ext_str}")

        # ── 第2阶段: 补充元数据 ──
        print(f"\n  获取课程元数据（总章节/总时长）...")
        need_meta = [c for c in courses if not (c.get("lectures_total") and c.get("total_hours"))]
        if need_meta:
            print(f"  需要补充 {len(need_meta)} 门课程的元数据...")
            for i, c in enumerate(need_meta):
                print(f"    ({i+1}/{len(need_meta)}) {c['name'][:40]}...")
                await fetch_course_metadata(page, c)

        # 保存到文件
        output = {
            "fetched_at": datetime.now().isoformat(),
            "count": len(courses),
            "courses": courses,
        }
        with open(COURSES_FILE, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n  已保存到 {COURSES_FILE}")

        await browser.close()
        return courses


if __name__ == "__main__":
    print("═══ Udemy 课程列表抓取（增强版）═══")
    courses = asyncio.run(fetch_courses())
    print(f"\n  完成，共 {len(courses)} 门课程")
