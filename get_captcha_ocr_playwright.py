import re
import asyncio
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import ddddocr
from playwright.async_api import async_playwright, Page, BrowserContext


# ================== 配置区 ==================
CATEGORY_URL = "https://www.youneed.win/category/nodeshare"

# XPath / 选择器（Playwright 支持多种方式，这里混合使用更稳健）
CAPTCHA_IMG_SELECTOR = "img[src*='captcha'], img[alt*='验证码']"
CAPTCHA_INPUT_SELECTOR = "input[placeholder*='验证码'], input[name*='captcha'], input[id*='captcha']"
SUBMIT_BTN_SELECTOR = "button:has-text('确定'), button:has-text('提交'), button:has-text('验证'), button.submit"

MAX_RETRIES = 8
PROTECTED_CONTENT_MIN_LENGTH = 100
TIMEOUT = 30000  # 30秒


async def get_latest_node_url() -> str | None:
    """获取节点分享分类页最新的文章链接"""
    print("🔍 正在获取最新节点文章链接...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = await context.new_page()

        try:
            await page.goto(CATEGORY_URL, timeout=TIMEOUT, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=10000)

            # 使用你原来精确的选择器
            latest_link = await page.query_selector(
                "body > main > div > div.row > div.col-lg-8 > div:nth-child(2) > div > div.list-content > div.list-body > a"
            )

            if latest_link:
                href = await latest_link.get_attribute("href")
                title = await latest_link.get_attribute("title") or (await latest_link.inner_text()).strip()

                if href:
                    full_url = href if href.startswith("http") else f"https://www.youneed.win{href}"
                    print(f"✅ 找到最新文章：{title}")
                    print(f"   链接：{full_url}")
                    return full_url

            print("⚠️ 未找到最新文章链接")
            return None

        finally:
            await browser.close()


def ocr_with_cleaning(image_path: str) -> str:
    """改进的验证码 OCR 处理"""
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 二值化 + 轻度降噪
    _, binary = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
    kernel = np.ones((2, 2), np.uint8)
    clean_img = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    _, img_encoded = cv2.imencode('.png', clean_img)
    img_bytes = img_encoded.tobytes()

    ocr = ddddocr.DdddOcr(show_ad=False)
    result = ocr.classification(img_bytes)
    return result.strip()

async def dismiss_consent_banner(page: Page):
    """移除可能的 Cookie 同意弹窗"""
    try:
        consent = await page.query_selector("div.fc-message-root")
        if consent:
            await page.evaluate("el => el.remove()", consent)
            print("✅ 已移除 fc-message-root 弹窗")
    except:
        pass


async def solve_captcha(page: Page) -> bool:
    """处理一次验证码"""
    try:
        # 等待验证码图片出现
        captcha_img = await page.wait_for_selector(CAPTCHA_IMG_SELECTOR, timeout=15000)
        if not captcha_img:
            return False

        # 保存验证码图片
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"captcha_{timestamp}.png"

        # Playwright 直接截取元素为图片（比获取 src 更可靠）
        await captcha_img.screenshot(path=save_path)
        print(f"✅ 验证码图片已保存：{save_path}")

        # OCR 识别
        result = ocr_with_cleaning(save_path)
        print(f"🔍 OCR 识别结果：{result}")

        if not result or len(result) < 3:
            print("⚠️ OCR 识别结果过短，可能失败")
            return False

        # 输入验证码
        input_box = await page.wait_for_selector(CAPTCHA_INPUT_SELECTOR, timeout=10000)
        await input_box.scroll_into_view_if_needed()
        await input_box.fill(result)
        print(f"✅ 已输入验证码：{result}")

        # 点击提交按钮
        submit_btn = await page.wait_for_selector(SUBMIT_BTN_SELECTOR, timeout=8000)
        await submit_btn.click()
        print("✅ 已点击提交按钮")

        # 等待内容加载
        await asyncio.sleep(5)
        return True

    except Exception as e:
        print(f"⚠️ 处理验证码时出错：{e}")
        return False


async def extract_nodes(page: Page):
    """提取 protected-content 中的节点内容"""
    print("⏳ 正在提取 protected-content 内容...")

    try:
        protected_div = await page.wait_for_selector("div.protected-content", timeout=15000)

        # 滚动确保内容完全加载
        await protected_div.scroll_into_view_if_needed()
        await page.evaluate("""
            el => {
                el.scrollTop = el.scrollHeight;
                el.querySelectorAll('pre').forEach(pre => pre.scrollTop = pre.scrollHeight);
            }
        """, protected_div)

        await asyncio.sleep(3)

        # 获取完整文本
        node_content = await protected_div.inner_text()

        if len(node_content) < 500:
            node_content = await page.evaluate("el => el.textContent", protected_div)

        print(f"✅ 提取成功！内容长度：{len(node_content):,} 字符")

        # 保存原始内容
        Path("node_content.txt").write_text(node_content, encoding="utf-8")
        print(f"✅ 完整内容已保存到 node_content.txt")

        # 清洗节点
        clean_nodes_to_subfile(node_content)

    except Exception as e:
        print(f"❌ 提取节点失败：{e}")


def clean_nodes_to_subfile(content: str, output_file: str = "v2.txt"):
    """从文本中提取有效节点并保存"""
    lines = content.splitlines()
    clean_lines = []

    for line in lines:
        stripped = line.strip()
        if re.match(r'^(ss://|vmess://|vless://|trojan://|hysteria2://)', stripped, re.IGNORECASE):
            clean_lines.append(stripped)

    if clean_lines:
        Path(output_file).write_text("\n".join(clean_lines), encoding="utf-8")
        print(f"✅ 节点清洗完成！共提取 {len(clean_lines)} 个有效节点 → {output_file}")
    else:
        print("⚠️ 未找到有效节点")


async def main():
    print("🚀 YouNeed.Win 节点自动获取工具（Playwright版）启动...\n")

    latest_url = await get_latest_node_url()
    if not latest_url:
        print("❌ 无法获取最新文章地址，程序退出")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # 改为 False 便于调试，正式可改 True
        context = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        try:
            print(f"🌐 正在打开文章页面：{latest_url}")
            await page.goto(latest_url, timeout=TIMEOUT, wait_until="domcontentloaded")

            for attempt in range(1, MAX_RETRIES + 1):
                print(f"\n📌 第 {attempt}/{MAX_RETRIES} 次尝试验证...")

                await dismiss_consent_banner(page)

                success = await solve_captcha(page)

                if not success:
                    if attempt < MAX_RETRIES:
                        print("🔄 验证失败，刷新页面重试...")
                        await page.reload(timeout=TIMEOUT)
                        await asyncio.sleep(8)
                        continue
                    else:
                        print("⛔ 达到最大重试次数")
                        break

                # 检查是否解锁成功
                try:
                    protected = await page.query_selector("div.protected-content")
                    if protected:
                        content_len = len((await protected.inner_text()).strip())
                        print(f"   当前 protected-content 长度：{content_len} 字符")

                        if content_len > PROTECTED_CONTENT_MIN_LENGTH:
                            print("🎉 验证成功！开始提取节点...")
                            await extract_nodes(page)
                            break
                except:
                    pass

                if attempt < MAX_RETRIES:
                    print("🔄 内容未完全解锁，刷新重试...")
                    await page.reload(timeout=TIMEOUT)
                    await asyncio.sleep(10)

        except Exception as e:
            print(f"❌ 程序运行出错：{e}")
        finally:
            print("\n🎉 任务完成！浏览器将在 15 秒后关闭（便于你查看结果）")
            await asyncio.sleep(15)
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())