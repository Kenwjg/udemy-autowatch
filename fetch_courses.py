#!/usr/bin/env python3
"""
抓取 Udemy 已注册课程列表。
打开 "My Learning" 页面，提取所有课程的名称和跳转 URL。
结果保存到 ~/udemy_courses.json
"""
import asyncio
import json
import os
from datetime import datetime

from playwright.async_api import async_playwright

PROFILE = os.path.expanduser("~/Library/Application Support/Udemy-AutoWatch-Chrome")
COURSES_FILE = os.path.expanduser("~/udemy_courses.json")

# Udemy Business 的 "我的学习" 页面
MY_LEARNING_URL = "https://your-org.udemy.com/home/my-courses/learning/"


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
                """() => document.querySelectorAll('[data-purpose="course-card-skeleton"]').length"""
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

        # 提取课程信息
        print("  提取课程信息...")
        js_extract = """
        () => {
            const results = [];
            const seen = new Set();
            
            const links = document.querySelectorAll('a[href*="course-dashboard-redirect"]');
            links.forEach(link => {
                const href = link.getAttribute('href') || '';
                if (!href || seen.has(href)) return;
                
                let url = href;
                if (href.startsWith('/')) {
                    url = window.location.origin + href;
                }
                
                let name = (link.textContent || '').trim();
                const h3 = link.closest('h3');
                if (h3) {
                    const h3Text = h3.textContent.trim();
                    if (h3Text.length > name.length) {
                        name = h3Text;
                    }
                }
                
                let progress = '';
                const card = link.closest('[class*="course-card"]') || link.closest('div');
                if (card) {
                    const meter = card.querySelector('[data-purpose="meter"]');
                    if (meter) {
                        progress = meter.getAttribute('aria-valuenow') || meter.textContent.trim();
                    }
                    const progTexts = card.querySelectorAll('[class*="progress"]');
                    progTexts.forEach(pt => {
                        const txt = pt.textContent.trim();
                        if (txt.includes('%')) {
                            progress = txt.replace('%', '').trim();
                        }
                    });
                }
                
                seen.add(href);
                results.push({ name, url, progress });
            });
            
            return results;
        }
        """
        courses = await page.evaluate(js_extract)

        print(f"\n  找到 {len(courses)} 门课程:\n")
        for i, c in enumerate(courses):
            prog = f" [{c['progress']}%]" if c.get('progress') else ""
            print(f"    {i+1}. {c['name']}{prog}")
            print(f"       {c['url'][:80]}")

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
    print("═══ Udemy 课程列表抓取 ═══")
    courses = asyncio.run(fetch_courses())
    print(f"\n  完成，共 {len(courses)} 门课程")
