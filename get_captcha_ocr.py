from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
from datetime import datetime
from webdriver_manager.chrome import ChromeDriverManager
import base64

import ddddocr
import cv2
import numpy as np

# ================== 配置 ==================
URL = "https://www.youneed.win/2026-04-03%E6%9C%80%E6%96%B0%E5%85%8D%E8%B4%B9%E5%85%AC%E7%9B%8Ass-vmess-vless-trojan-hysteria2%E8%8A%82%E7%82%B9%E5%88%86%E4%BA%AB.html"
XPATH_CAPTCHA_IMG = "/html/body/main/div/div[2]/div[1]/div[1]/div[1]/div[2]/div/div[1]/div[1]/div/img"


def dismiss_consent_banner(driver):
    """自动移除 fc-consent-root 弹窗"""
    try:
        # 等待弹窗出现（最长等 8 秒）
        consent = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "body > div.fc-consent-root"))
        )

        # 方法1：直接用 JS 彻底移除整个弹窗（最干净）
        driver.execute_script("arguments[0].remove();", consent)
        print("✅ 已通过 JS 移除 fc-consent-root 弹窗")

        # 方法2（备用）：尝试点击“同意”按钮（如果移除失败）
        try:
            accept_btn = consent.find_element(By.XPATH, ".//button[contains(text(),'同意') or contains(text(),'接受') or contains(text(),'Accept')]")
            accept_btn.click()
            print("✅ 已点击同意按钮")
        except:
            pass

    except:
        print("ℹ️  未检测到 fc-consent-root 弹窗（可能已关闭或本次未出现）")


def main():
    chrome_options = Options()
    # chrome_options.add_argument("--headless")   # 需要无界面就取消注释
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        print("🚀 正在打开页面...")
        driver.get(URL)
        driver.maximize_window()

        # ================== 新增：移除同意弹窗 ==================
        dismiss_consent_banner(driver)

        print("⏳ 等待验证码图片加载...")
        captcha_img = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, XPATH_CAPTCHA_IMG))
        )

        img_src = captcha_img.get_attribute("src")
        print(f"✅ 验证码图片地址：{img_src[:100]}...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"captcha_{timestamp}.png"

        # ==== 支持 data:base64 ====
        if img_src.startswith("data:image"):
            header, base64_data = img_src.split(",", 1)
            image_data = base64.b64decode(base64_data)
            with open(save_path, "wb") as f:
                f.write(image_data)
            print(f"✅ 验证码图片已保存（base64解码）：{save_path}")
        else:
            import requests
            response = requests.get(img_src, timeout=10)
            with open(save_path, "wb") as f:
                f.write(response.content)
            print(f"✅ 验证码图片已保存（网络下载）：{save_path}")

        # OCR 识别
        result = ocr_with_cleaning(save_path)
        print(f"{save_path}：🔍 处理后识别结果：{result}")
        print("🎉 保存完成！浏览器会保持打开 30 秒，你可以直接输入验证码。")
        time.sleep(30)

    except Exception as e:
        print(f"❌ 发生错误：{e}")
    finally:
        # driver.quit()  # 需要自动关闭就取消注释
        pass


def ocr_captcha(image_path):
    ocr = ddddocr.DdddOcr(show_ad=False)
    with open(image_path, 'rb') as f:
        img_bytes = f.read()
    res = ocr.classification(img_bytes)
    return res


def ocr_with_cleaning(image_path):
    # 1. 读取图片
    img = cv2.imread(image_path)

    # 2. 转为灰度图
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. 二值化处理（关键步）
    # 这里的 140 是阈值，可以根据识别情况微调：
    # 调低（如 100）会去掉更多浅色，但也可能把数字弄断
    # 调高（如 160）会保留更多细节，但也可能留下干扰线
    _, binary = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)

    # 4. 降噪（可选）：去除小的杂点
    kernel = np.ones((2, 2), np.uint8)
    clean_img = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    # 5. 将处理后的图片转为字节流给 ddddocr
    _, img_encoded = cv2.imencode('.png', clean_img)
    img_bytes = img_encoded.tobytes()

    # 预览处理结果（调试用，正式跑的时候注释掉）
    # cv2.imshow('Cleaned', clean_img)
    # cv2.waitKey(0)

    ocr = ddddocr.DdddOcr(show_ad=False)
    res = ocr.classification(img_bytes)
    return res


if __name__ == "__main__":
    main()
