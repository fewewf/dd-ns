import os
import requests
import csv
import dns.resolver
import random

# === 配置部分 ===
RECORD_NAME = "yx1"
TARGET_DOMAIN = "cf.877774.xyz"  # 你要查询的域名

# 获取 Secrets 环境变量
api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
zone_id = os.environ.get("CF_ZONE_ID")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

headers = {
    "Authorization": f"Bearer {api_token}",
    "Content-Type": "application/json",
}

# === DNS 查询函数 ===

def get_target_domain_ips(domain):
    """获取目标域名的所有A记录IP地址"""
    try:
        answers = dns.resolver.resolve(domain, 'A')
        return [str(r) for r in answers]
    except dns.resolver.NoAnswer:
        print(f"域名 {domain} 没有A记录")
        return []
    except dns.resolver.NXDOMAIN:
        print(f"域名 {domain} 不存在")
        return []
    except Exception as e:
        print(f"DNS查询出错: {e}")
        return []

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
    elif result.get("errors") and any(e.get("code") == 81058 for e in result["errors"]):
        print(f"记录已存在: {name} => {ip}")
    else:
        raise Exception(f"创建失败: {resp.text}")

# === 工具函数 ===

def get_ips_from_txt(file, count=3):
    """从txt文件中获取随机的IP"""
    with open(file, 'r', encoding='utf-8') as f:
        ips = [line.strip() for line in f if line.strip()]
    
    if len(ips) < count:
        raise Exception(f"文件中可用的IP数量少于 {count}")
    
    # 随机选择count个IP
    selected_ips = random.sample(ips, count)
    return selected_ips

def delete_all_yx1_records():
    """删除所有yx1开头的A记录"""
    records = get_existing_dns_records()
    for r in records:
        if r.get("type") == "A" and "yx1" in r.get("name", ""):
            delete_dns_record(r.get("id"))

def log_existing_yx1_records():
    """记录现有的yx1记录"""
    records = get_existing_dns_records()
    yx1 = [r for r in records if r.get("type") == "A" and r.get("name") == RECORD_NAME]
    
    for r in yx1:
        print(f"{r['name']} => {r['content']} (ID: {r['id']})")

# === 主函数 ===

def main():
    try:
        print("当前存在的记录:")
        log_existing_yx1_records()

        # 获取从 test.txt 文件中随机选择的 3 个 IP
        selected_ips = get_ips_from_txt('test.txt', count=3)
        print(f"从 test.txt 随机选择的 IP 地址: {selected_ips}")

        print("即将删除旧记录...")
        delete_all_yx1_records()

        print("开始创建新记录...")
        for ip in selected_ips:
            create_dns_record(ip, RECORD_NAME)

        # 发送通知
        message = f"已为 {RECORD_NAME} 创建 {len(selected_ips)} 条记录，同步自 test.txt:\n" + "\n".join(selected_ips)
        send_telegram_message(message)
        
    except Exception as e:
        print("程序运行出错:", e)
        send_telegram_message(f"程序运行出错:\n{e}")

if __name__ == "__main__":
    main()
