from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
import time
import os
import requests
import re
import csv

# Telegram 设置
def escape_markdown_v2(text):
    """转义 Telegram MarkdownV2 特殊字符"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def send_telegram_message(content):
    """发送 Telegram 消息，支持 MarkdownV2 格式"""
    escaped_content = escape_markdown_v2(content)
    content_with_line_breaks = escaped_content.replace("\n", "  \n")  # MarkdownV2 换行
    spoiler_content = f'||{content_with_line_breaks}||'  # 添加剧透效果
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': spoiler_content,
        'parse_mode': 'MarkdownV2'
    }
    response = requests.post(url, data=data)
    if response.status_code != 200:
        print(f"发送消息到 Telegram 时发生错误: {response.text}")

# 获取 GitHub Secrets
api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
zone_id = os.environ.get("CF_ZONE_ID")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
name = "yx1"
headers = {
    "Authorization": f"Bearer {api_token}",
    "Content-Type": "application/json",
}

def delete_dns_record(record_id):
    try:
        delete_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
        response = requests.delete(delete_url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to delete DNS record with ID {record_id}: {response.text}")
        print(f"成功删除 DNS 记录 ID {record_id}")
    except Exception as e:
        print(f"Exception occurred while deleting DNS record with ID {record_id}: {str(e)}")

def get_existing_dns_records():
    """获取当前所有 DNS 记录"""
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch DNS records: {response.text}")
    return response.json().get("result", [])

def record_exists(name, ip):
    """检查指定的 DNS 记录是否已存在"""
    records = get_existing_dns_records()
    for record in records:
        if record["name"] == name and record["content"] == ip:
            return True
    return False

def create_dns_record(ip, record_name):
    """创建 DNS 记录"""
    try:
        if record_exists(record_name, ip):
            print(f"DNS 记录 {record_name} -> {ip} 已存在，跳过创建")
            return
        
        create_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        create_data = {
            "type": "A",
            "name": record_name,
            "content": ip,
            "ttl": 60,
            "proxied": False,
        }
        response = requests.post(create_url, headers=headers, json=create_data)
        if response.status_code != 200:
            raise Exception(f"Failed to create DNS record for IP {ip}: {response.text}")
        
        send_telegram_message(f"成功创建 DNS 记录: {record_name} ip:{ip}")
        print(f"成功创建 DNS 记录: {record_name} -> {ip}")
    except Exception as e:
        print(f"Exception occurred while creating DNS record for IP {ip}: {str(e)}")

def main():
    # 从result.csv获取前三个IP
    try:
        top_ips = get_top_ips_from_csv("result.csv", 3)
        if not top_ips:
            print("没有从CSV文件中获取到有效的IP地址")
            return

        print(f"获取到的前三个IP地址: {top_ips}")

        # 获取并删除旧的 DNS 记录
        records = get_existing_dns_records()
        for record in records:
            record_name = record.get("name", "")
            if record_name == name:  # 只删除与yx1完全匹配的记录
                delete_dns_record(record["id"])

        # 为每个 IP 创建新的 DNS 记录
        for ip in top_ips:
            create_dns_record(ip, name)
            print(f"成功创建 DNS 记录 {name} => {ip}")

        send_telegram_message(f"成功为 {name} 创建了 {len(top_ips)} 条 DNS 记录:\n" + "\n".join(top_ips))

    except Exception as e:
        print(f"程序运行出错: {str(e)}")
        send_telegram_message(f"程序运行出错: {str(e)}")

if __name__ == "__main__":
    main()
