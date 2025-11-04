import os
import time
import random
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# -------------------------------
log_buffer = []

def log(msg):
    print(msg)
    log_buffer.append(msg)
# -------------------------------

# 随机延迟函数
def random_delay(min_seconds=1, max_seconds=3):
    time.sleep(random.uniform(min_seconds, max_seconds))

# 模拟人类输入
def human_type(element, text):
    """模拟人类输入速度"""
    for char in text:
        element.type(char)
        time.sleep(random.uniform(0.08, 0.2))  # 随机输入间隔

# 模拟鼠标移动
def human_mouse_move(page, selector):
    """模拟人类鼠标移动"""
    element = page.query_selector(selector)
    if element:
        box = element.bounding_box()
        if box:
            # 随机移动路径
            x = box['x'] + box['width'] * random.uniform(0.3, 0.7)
            y = box['y'] + box['height'] * random.uniform(0.3, 0.7)
            
            # 添加随机移动点
            for _ in range(random.randint(1, 3)):
                offset_x = random.randint(-20, 20)
                offset_y = random.randint(-20, 20)
                page.mouse.move(x + offset_x, y + offset_y)
                random_delay(0.1, 0.3)
            
            page.mouse.move(x, y)
            random_delay(0.2, 0.5)

# 随机滚动页面
def random_scroll(page):
    """模拟人类滚动行为"""
    scroll_height = page.evaluate("document.body.scrollHeight")
    viewport_height = page.evaluate("window.innerHeight")
    
    if scroll_height > viewport_height:
        # 随机滚动几次
        for _ in range(random.randint(1, 3)):
            scroll_to = random.randint(0, scroll_height - viewport_height)
            page.evaluate(f"window.scrollTo({{top: {scroll_to}, behavior: 'smooth'}})")
            random_delay(0.5, 1.5)

# 设置更真实的浏览器上下文
def create_human_like_context(playwright):
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            '--no-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-features=VizDisplayCompositor',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding'
        ]
    )
    
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        locale='en-US',
        timezone_id='America/New_York'
    )
    
    # 添加额外的脚本以掩盖自动化特征
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
    """)
    
    return browser, context

# Telegram 推送函数
def send_tg_log():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️ Telegram 未配置，跳过推送")
        return

    utc_now = datetime.utcnow()
    beijing_now = utc_now + timedelta(hours=8)
    now_str = beijing_now.strftime("%Y-%m-%d %H:%M:%S") + " UTC+8"

    final_msg = f"执行日志\n🕒 {now_str}\n\n" + "\n".join(log_buffer)

    for i in range(0, len(final_msg), 3900):
        chunk = final_msg[i:i+3900]
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/sendMessage",
                params={"chat_id": chat_id, "text": chunk},
                timeout=10
            )
            if resp.status_code == 200:
                print(f"✅ Telegram 推送成功 [{i//3900 + 1}]")
            else:
                print(f"⚠️ Telegram 推送失败 [{i//3900 + 1}]: HTTP {resp.status_code}, 响应: {resp.text}")
        except Exception as e:
            print(f"⚠️ Telegram 推送异常 [{i//3900 + 1}]: {e}")

# 从环境变量解析多个账号
accounts_env = os.environ.get("SITE_ACCOUNTS", "")
accounts = []

for item in accounts_env.split("$"):
    if item.strip():
        try:
            username, password = item.split("&", 1)
            accounts.append({"username": username.strip(), "password": password.strip()})
        except ValueError:
            log(f"⚠️ 忽略格式错误的账号项: {item}")

fail_msgs = [
    "Invalid credentials.",
    "Not connected to server.",
    "Error with the login: login size should be between 2 and 50 (currently: 1)"
]

def login_account(playwright, USER, PWD):
    log(f"🚀 开始登录账号: {USER}")
    try:
        browser, context = create_human_like_context(playwright)
        page = context.new_page()

        # 访问主页前先随机延迟
        random_delay(2, 4)
        
        # 访问主页
        page.goto("https://www.netlib.re/", wait_until="networkidle")
        random_delay(3, 6)
        
        # 随机滚动页面
        random_scroll(page)
        
        # 模拟人类点击登录按钮
        human_mouse_move(page, "text=Login")
        random_delay(1, 2)
        page.get_by_text("Login").click()
        
        # 等待页面加载
        page.wait_for_load_state("networkidle")
        random_delay(2, 4)
        
        # 随机滚动登录页面
        random_scroll(page)
        
        # 填写用户名
        human_mouse_move(page, '[name="Username"]')
        random_delay(0.5, 1)
        username_field = page.get_by_role("textbox", name="Username")
        username_field.click()
        random_delay(0.3, 0.7)
        human_type(username_field, USER)
        
        # 填写密码
        human_mouse_move(page, '[name="Password"]')
        random_delay(0.5, 1)
        password_field = page.get_by_role("textbox", name="Password")
        password_field.click()
        random_delay(0.3, 0.7)
        human_type(password_field, PWD)
        
        # 提交前随机延迟
        random_delay(1, 2)
        
        # 点击提交按钮
        human_mouse_move(page, 'button[name="Validate"]')
        random_delay(0.5, 1)
        page.get_by_role("button", name="Validate").click()
        
        # 等待响应
        page.wait_for_load_state("networkidle")
        random_delay(3, 5)
        
        # 随机滚动结果页面
        random_scroll(page)

        success_text = "You are the exclusive owner of the following domains."
        if page.query_selector(f"text={success_text}"):
            log(f"✅ 账号 {USER} 登录成功")
            random_delay(2, 4)  # 成功后在页面停留一段时间
        else:
            failed_msg = None
            for msg in fail_msgs:
                if page.query_selector(f"text={msg}"):
                    failed_msg = msg
                    break
            if failed_msg:
                log(f"❌ 账号 {USER} 登录失败: {failed_msg}")
            else:
                # 检查是否有其他错误信息
                error_elements = page.query_selector_all('.error, .alert, [class*="error"], [class*="alert"]')
                if error_elements:
                    for error in error_elements[:2]:  # 只取前两个错误元素
                        error_text = error.inner_text()
                        if error_text and len(error_text) < 100:  # 限制错误信息长度
                            log(f"❌ 账号 {USER} 登录失败: {error_text}")
                            break
                else:
                    log(f"❌ 账号 {USER} 登录失败: 未知错误")

        context.close()
        browser.close()

    except Exception as e:
        log(f"❌ 账号 {USER} 登录异常: {e}")

def run():
    with sync_playwright() as playwright:
        for acc in accounts:
            login_account(playwright, acc["username"], acc["password"])
            # 账号间随机延迟
            time.sleep(random.randint(10, 30))

if __name__ == "__main__":
    run()
    send_tg_log()  # 发送日志
