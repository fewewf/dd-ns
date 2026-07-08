import os
import requests
import random

# === 配置部分 ===
RECORD_NAME = "yx1"

# 获取 Secrets 环境变量
api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
zone_ids = os.environ.get("CF_ZONE_ID").split(',')  # 支持多个 CF_ZONE_ID，使用逗号分隔
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

def get_existing_dns_records(zone_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json().get("result", [])

def delete_dns_record(zone_id, record_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    resp = requests.delete(url, headers=headers)
    if resp.status_code == 200:
        print(f"已删除记录 ID: {record_id}")
    else:
        print(f"删除记录失败 ID: {record_id}，响应: {resp.text}")

def create_dns_record(zone_id, ip, name):
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

    return random.sample(ips, count)

def delete_all_yx1_records(zone_id):
    """删除所有 yx1 相关的 A 记录"""
    records = get_existing_dns_records(zone_id)
    for r in records:
        if r.get("type") == "A" and "yx1" in r.get("name", ""):
            delete_dns_record(zone_id, r.get("id"))

def log_existing_yx1_records(zone_id):
    """记录现有的 yx1 记录"""
    records = get_existing_dns_records(zone_id)
    yx1 = [r for r in records if r.get("type") == "A" and r.get("name") == RECORD_NAME]

    for r in yx1:
        print(f"{r['name']} => {r['content']} (ID: {r['id']})")

# === 主函数 ===

def main():
    try:
        all_selected_ips = get_ips_from_txt('test.txt', count=3)
        print(f"从 test.txt 随机选择的 IP 地址: {all_selected_ips}")

        summary = []   # <<< 用来汇总所有 zone 的结果

        for zone_id in zone_ids:
            zone_id = zone_id.strip()
            print(f"\n正在处理 Zone ID")

            log_existing_yx1_records(zone_id)

            delete_all_yx1_records(zone_id)

            for ip in all_selected_ips:
                create_dns_record(zone_id, ip, RECORD_NAME)

            # 本 zone 处理结果加入汇总
            summary.append(
                f"Zone {zone_id} 完成，创建 {len(all_selected_ips)} 条记录"
            )

        # ✅ 所有 zone 完成后统一发送一次
        final_message = (
            f"DNS 批量更新完成\n"
            f"记录名: {RECORD_NAME}\n"
            f"IP:\n" +
            "\n".join(all_selected_ips) +
            "\n\n执行结果:\n" +
            "\n".join(summary)
        )

        #send_telegram_message(final_message)

    except Exception as e:
        print("程序运行出错:", e)
        send_telegram_message(f"程序运行出错:\n{e}")
if __name__ == "__main__":
    main()
