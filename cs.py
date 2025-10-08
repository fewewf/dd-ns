import os
import requests
import csv
import dns.resolver

# === 配置部分 ===
RECORD_NAME = "yx1"
TARGET_DOMAIN = "sjc.o00o.ooo"  # 你要查询的域名

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

def get_ips_from_csv(file, start=2, count=5):
    """从CSV文件获取IP（保留原功能）"""
    ips = []
    with open(file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)  # 跳过标题行
        for i, row in enumerate(reader):
            if i >= start and row and row[0].strip():
                ips.append(row[0].strip())
            if len(ips) >= count:
                break
    return ips

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

        # 获取目标域名的所有IP
        target_ips = get_target_domain_ips(TARGET_DOMAIN)
        if not target_ips:
            raise Exception(f"无法获取 {TARGET_DOMAIN} 的IP地址")

        print(f"从 {TARGET_DOMAIN} 获取的IP地址:", target_ips)

        print("即将删除旧记录...")
        delete_all_yx1_records()

        print("开始创建新记录...")
        for ip in target_ips:
            create_dns_record(ip, RECORD_NAME)

        # 发送通知
        message = f"已为 {RECORD_NAME} 创建 {len(target_ips)} 条记录，同步自 {TARGET_DOMAIN}:\n" + "\n".join(target_ips)
        send_telegram_message(message)
        
    except Exception as e:
        print("程序运行出错:", e)
        send_telegram_message(f"程序运行出错:\n{e}")

if __name__ == "__main__":
    main()
