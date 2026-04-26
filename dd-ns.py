import os
import requests
import csv
import traceback

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
    try:
        escaped = escape_markdown_v2(text).replace("\n", "  \n")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': f'||{escaped}||',
            'parse_mode': 'MarkdownV2'
        }
        requests.post(url, data=data, timeout=10)
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
        raise Exception(f"删除记录失败 ID: {record_id}，响应: {resp.text}")

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
    elif result.get("errors") and any(e.get("code") == 81058 for e in result["errors"]):
        print(f"记录已存在: {name} => {ip}")
    else:
        raise Exception(f"创建失败: {resp.text}")

# === 工具函数 ===

def get_ips_from_csv(file, start=2, count=5):
    ips = []
    with open(file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)
        for i, row in enumerate(reader):
            if i >= start and row and row[0].strip():
                ips.append(row[0].strip())
            if len(ips) >= count:
                break
    return ips

def delete_all_yx1_records():
    records = get_existing_dns_records()
    for r in records:
        if r.get("type") == "A" and "yx1" in r.get("name", ""):
            delete_dns_record(r.get("id"))

def log_existing_yx1_records():
    records = get_existing_dns_records()
    yx1 = [r for r in records if r.get("type") == "A" and r.get("name") == RECORD_NAME]
    for r in yx1:
        print(f"{r['name']} => {r['content']} (ID: {r['id']})")

# === 主函数 ===

def main():
    log_existing_yx1_records()

    top_ips = get_ips_from_csv("result.csv", start=2, count=5)
    if not top_ips:
        raise Exception("CSV 中未读取到有效 IP")

    print("即将删除旧记录...")
    delete_all_yx1_records()

    print("开始创建新记录...")
    for ip in top_ips:
        create_dns_record(ip, RECORD_NAME)

    print(f"完成：已创建 {len(top_ips)} 条记录")

# === 程序入口 ===

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_msg = traceback.format_exc()
        print("程序运行出错:\n", error_msg)

        send_telegram_message(
            f"DNS 更新失败 ⚠️\n\n错误信息:\n{error_msg}"
        )
