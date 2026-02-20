import os
import requests
import random
import datetime

# ===================== 配置 =====================
RECORD_NAME = "yx1"
SOURCE_URL = "https://ddx.snu.cc/JP"

api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
zone_ids = os.environ.get("CF_ZONE_ID").split(",")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

headers = {
    "Authorization": f"Bearer {api_token}",
    "Content-Type": "application/json",
}

# ===================== 日志 =====================
def log(msg):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")

# ===================== Telegram =====================
def escape_markdown_v2(text):
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)

def send_telegram_message(text):
    escaped = escape_markdown_v2(text).replace("\n", "  \n")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"||{escaped}||",
        "parse_mode": "MarkdownV2"
    }
    try:
        requests.post(url, data=data, timeout=15)
    except Exception as e:
        log(f"Telegram发送失败: {e}")

# ===================== Cloudflare API =====================
def get_existing_dns_records(zone_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json().get("result", [])

def delete_dns_record(zone_id, record_id, ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    resp = requests.delete(url, headers=headers)
    if resp.status_code == 200:
        log(f"[Zone {zone_id}] 删除 IP {ip}")
    else:
        log(f"[Zone {zone_id}] 删除失败 {ip} → {resp.text}")

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
        log(f"[Zone {zone_id}] 新增 IP {ip}")
    else:
        log(f"[Zone {zone_id}] 新增失败 {ip} → {resp.text}")

# ===================== IP 源 =====================
def fetch_ips_by_port(url):
    log("获取远程IP列表")
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()

    port_map = {443: [], 8443: [], 2053: []}

    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            ip_port = line.split("#")[0]
            ip, port = ip_port.split(":")
            port = int(port)

            if port in port_map:
                port_map[port].append(ip)
        except:
            continue

    for p, lst in port_map.items():
        log(f"端口 {p} 可用IP {len(lst)} 个")

    return port_map

def select_ips_per_port(port_map, count=2):
    selected = {}
    for port, ips in port_map.items():
        if len(ips) < count:
            raise Exception(f"端口 {port} IP不足")
        selected[port] = random.sample(ips, count)
        log(f"端口 {port} 选中 {selected[port]}")
    return selected

# ===================== DNS 差异更新 =====================
def diff_update_dns(zone_id, desired_ips):
    """
    仅更新变化IP
    """
    records = get_existing_dns_records(zone_id)

    existing = {}
    for r in records:
        if r.get("type") == "A" and r.get("name") == RECORD_NAME:
            existing[r["content"]] = r["id"]

    existing_ips = set(existing.keys())
    desired_ips = set(desired_ips)

    to_delete = existing_ips - desired_ips
    to_add = desired_ips - existing_ips
    unchanged = existing_ips & desired_ips

    log(f"[Zone {zone_id}] 当前IP {list(existing_ips)}")
    log(f"[Zone {zone_id}] 目标IP {list(desired_ips)}")

    for ip in to_delete:
        delete_dns_record(zone_id, existing[ip], ip)

    for ip in to_add:
        create_dns_record(zone_id, ip, RECORD_NAME)

    log(f"[Zone {zone_id}] 保持不变 {list(unchanged)}")

    return {
        "add": list(to_add),
        "delete": list(to_delete),
        "keep": list(unchanged)
    }

# ===================== 主流程 =====================
def main():
    try:
        ports = [443, 8443, 2053]

        if len(zone_ids) < 3:
            raise Exception("需要3个CF_ZONE_ID")

        port_map = fetch_ips_by_port(SOURCE_URL)
        selected = select_ips_per_port(port_map, 2)

        summary = []

        for i, port in enumerate(ports):
            zone_id = zone_ids[i].strip()
            ips = selected[port]

            log(f"=== 端口 {port} → Zone {zone_id} ===")

            result = diff_update_dns(zone_id, ips)

            summary.append(
                f"{port}: +{len(result['add'])} -{len(result['delete'])} ={len(result['keep'])}"
            )

        msg = (
            "DNS差异更新完成\n"
            f"记录: {RECORD_NAME}\n\n"
            "分配IP:\n"
            f"443 {selected[443]}\n"
            f"8443 {selected[8443]}\n"
            f"2053 {selected[2053]}\n\n"
            "结果:\n" + "\n".join(summary)
        )

        send_telegram_message(msg)

        log("全部完成")

    except Exception as e:
        log(f"程序异常: {e}")
        send_telegram_message(f"程序异常:\n{e}")

if __name__ == "__main__":
    main()
