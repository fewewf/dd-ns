import os
import requests
import random
import datetime
import time

# ===================== 配置 =====================
RECORD_NAME = "yx1"
SOURCE_URL = "https://ddx.snu.cc/JP"
CF_DELAY = 1.2  # Cloudflare API延时(秒)

api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
zone_ids = os.environ.get("CF_ZONE_ID").split(",")

headers = {
    "Authorization": f"Bearer {api_token}",
    "Content-Type": "application/json",
}

# ===================== 日志 =====================
def log(msg):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

# ===================== Cloudflare =====================
def get_existing_dns_records(zone_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    time.sleep(CF_DELAY)
    return resp.json().get("result", [])

def delete_dns_record(zone_id, record_id, ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    requests.delete(url, headers=headers)
    log(f"[Zone {zone_id}] 删除 {ip}")
    time.sleep(CF_DELAY)

def create_dns_record(zone_id, ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    data = {
        "type": "A",
        "name": RECORD_NAME,
        "content": ip,
        "ttl": 60,
        "proxied": False,
    }
    requests.post(url, headers=headers, json=data)
    log(f"[Zone {zone_id}] 新增 {ip}")
    time.sleep(CF_DELAY)

# ===================== IP源 =====================
def fetch_ips_by_port():
    log("获取远程IP")
    resp = requests.get(SOURCE_URL, timeout=20)
    resp.raise_for_status()

    port_map = {443: [], 8443: [], 2053: []}

    for line in resp.text.splitlines():
        try:
            ip_port = line.split("#")[0]
            ip, port = ip_port.split(":")
            port = int(port)
            if port in port_map:
                port_map[port].append(ip)
        except:
            continue

    for p in port_map:
        log(f"端口 {p} IP数 {len(port_map[p])}")

    return port_map

def select_ips(port_map, count=2):
    selected = {}
    for port, ips in port_map.items():
        if len(ips) < count:
            log(f"⚠️ 端口 {port} IP不足，跳过")
            continue
        selected[port] = random.sample(ips, count)
        log(f"端口 {port} 选中 {selected[port]}")
    return selected

# ===================== 差异更新 =====================
def diff_update_dns(zone_id, desired_ips):
    records = get_existing_dns_records(zone_id)

    existing = {}
    for r in records:
        if r.get("type") == "A":
            name = r.get("name", "")
            # 修复：匹配 yx1 子域
            if name.split(".")[0] == RECORD_NAME:
                existing[r["content"]] = r["id"]

    existing_ips = set(existing.keys())
    desired_ips = set(desired_ips)

    log(f"[Zone {zone_id}] 当前 {list(existing_ips)}")
    log(f"[Zone {zone_id}] 目标 {list(desired_ips)}")

    to_delete = existing_ips - desired_ips
    to_add = desired_ips - existing_ips
    keep = existing_ips & desired_ips

    for ip in to_delete:
        delete_dns_record(zone_id, existing[ip], ip)

    for ip in to_add:
        create_dns_record(zone_id, ip)

    log(f"[Zone {zone_id}] 保持 {list(keep)}")

# ===================== 主流程 =====================
def main():
    ports = [443, 8443, 2053]

    try:
        port_map = fetch_ips_by_port()
        selected = select_ips(port_map, 2)

        for i, port in enumerate(ports):
            if port not in selected:
                log(f"跳过端口 {port}（IP不足）")
                continue

            zone_id = zone_ids[i].strip()
            ips = selected[port]

            log(f"=== 端口 {port} → Zone {zone_id} ===")
            diff_update_dns(zone_id, ips)

        log("全部完成")

    except Exception as e:
        log(f"异常: {e}")

if __name__ == "__main__":
    main()
