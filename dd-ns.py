import os
import requests
import csv

# === 配置部分 ===
RECORD_NAME = "yx1"

# 获取 Secrets 环境变量
api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
zone_id = os.environ.get("CF_ZONE_ID")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

headers = {
    "Authorization": f"Bearer {api_token}",
    "Content-Type": "application/json",
}

# === Telegram 相关函数 ===

def escape_markdown_v2(text):
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)

def send_telegram_message(text):
    escaped = escape_markdown_v2(text).replace("\n", "  \n")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': f'||{escaped}||',
        'parse_mode': 'MarkdownV2'
    }
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("发送 Telegram 消息失败:", e)

# === Cloudflare API 操作 ===

def get_existing_dns_records():
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json().get("result", [])

def delete_dns_record(record_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    resp = requests.delete(url, headers=headers)
    if resp.status_code == 200:
        print(f"已删除记录 ID: {record_id}")
    else:
        print(f"删除记录失败 ID: {record_id}，响应: {resp.text}")

def create_dns_record(ip, name):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    data = {
        "type": "A",
        "name": name,
        "content": ip,
        "ttl": 60,
        "proxied": False,
    }
    resp = requests.post(url, headers=headers, json=data)
    result = resp.json()
    if result.get("success"):
        print(f"成功创建: {name} => {ip}")
        send_telegram_message(f"成功创建 DNS 记录: {name} => {ip}")
    elif result.get("errors") and any(e.get("code") == 81058 for e in result["errors"]):
        print(f"记录已存在: {name} => {ip}")
    else:
        raise Exception(f"创建失败: {resp.text}")

# === 工具函数 ===

def get_top_ips_from_csv(file, count=3):
    ips = []
    with open(file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if row and row[0].strip():
                ips.append(row[0].strip())
            if len(ips) >= count:
                break
    return ips

def delete_all_yx1_records():
    records = get_existing_dns_records()
    for r in records:
        if r.get("type") == "A" and r.get("name") == RECORD_NAME:
            delete_dns_record(r.get("id"))

def log_existing_yx1_records():
    records = get_existing_dns_records()
    yx1 = [r for r in records if r.get("type") == "A" and r.get("name") == RECORD_NAME]
    print(f"当前 yx1 记录数量: {len(yx1)}")
    for r in yx1:
        print(f"{r['name']} => {r['content']} (ID: {r['id']})")

# === 主函数 ===

def main():
    try:
        log_existing_yx1_records()

        top_ips = get_top_ips_from_csv("result.csv", 3)
        if not top_ips:
            raise Exception("CSV 中未读取到有效 IP")

        print("即将删除旧记录...")
        delete_all_yx1_records()

        print("开始创建新记录...")
        for ip in top_ips:
            create_dns_record(ip, RECORD_NAME)

        send_telegram_message(f"已为 {RECORD_NAME} 创建新 A 记录：\n" + "\n".join(top_ips))
    except Exception as e:
        print("程序运行出错:", e)
        send_telegram_message(f"程序运行出错:\n{e}")

if __name__ == "__main__":
    main()
