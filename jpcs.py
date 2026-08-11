import os
import requests
import datetime
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 配置
# ============================================================

# IP源
SOURCE_URL = "https://ddx.snu.cc/JP"

# Cloudflare
RECORD_NAME = "yx1"
CF_DELAY = 1.2

# 检测数量：找到多少个有效IP后停止
VALID_IP_COUNT = 3

# 检测并发数
MAX_WORKERS = 10

# API Token参数
CHECK_TOKEN = "zfwkn"

# 环境变量
CF_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
CF_ZONE_ID_ENV = os.environ.get("CF_ZONE_ID")
CHECK_API_URL = os.environ.get("CHECK_API_URL")


# ============================================================
# 全局停止事件
# ============================================================

stop_event = threading.Event()


# ============================================================
# 日志
# ============================================================

def log(msg):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# ============================================================
# 参数检查
# ============================================================

def check_config():
    if not CF_API_TOKEN:
        raise ValueError("缺少环境变量 CLOUDFLARE_API_TOKEN")

    if not CF_ZONE_ID_ENV:
        raise ValueError("缺少环境变量 CF_ZONE_ID")

    if not CHECK_API_URL:
        raise ValueError("缺少环境变量 CHECK_API_URL")

    zone_ids = [
        zone.strip()
        for zone in CF_ZONE_ID_ENV.split(",")
        if zone.strip()
    ]

    if not zone_ids:
        raise ValueError("CF_ZONE_ID 没有有效的 Zone ID")

    return zone_ids


# ============================================================
# HTTP Session
# ============================================================

session = requests.Session()

cf_headers = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json",
}


# ============================================================
# 第一步：下载IP列表
# ============================================================

def fetch_source():
    log(f"下载IP列表: {SOURCE_URL}")

    response = session.get(
        SOURCE_URL,
        timeout=20
    )

    response.raise_for_status()

    log(f"IP列表下载成功，共 {len(response.text.splitlines())} 行")

    return response.text


# ============================================================
# 第二步：提取所有443端口IP
#
# 格式：
# 103.25.100.129:443#837-日本
# ============================================================

def extract_443_ips(text):
    ips = []

    for line_num, line in enumerate(text.splitlines(), 1):
        line = line.strip()

        if not line:
            continue

        try:
            # 只取 # 前面的部分
            ip_port = line.split("#", 1)[0].strip()

            # 使用最后一个 : 分割，避免以后兼容IPv6时太容易出问题
            ip, port = ip_port.rsplit(":", 1)

            ip = ip.strip()
            port = port.strip()

            if port == "443":
                ips.append(ip)

        except Exception:
            log(f"跳过格式错误，第 {line_num} 行: {line}")
            continue

    # 去重，同时保持原始顺序
    ips = list(dict.fromkeys(ips))

    log(f"提取到 {len(ips)} 个443端口IP")

    for i, ip in enumerate(ips, 1):
        log(f"  {i:02d}. {ip}:443")

    return ips


# ============================================================
# 第三步：检测单个IP
# ============================================================

def check_proxy(ip):
    if stop_event.is_set():
        return None

    proxy_url = f"{ip}:443"

    api_url = (
        f"{CHECK_API_URL.rstrip('/')}"
        f"/check"
        f"?proxyip={proxy_url}"
        f"&token={CHECK_TOKEN}"
    )

    try:
        response = session.get(
            api_url,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        success = data.get("success", False)

        result = {
            "ip": ip,
            "port": 443,
            "success": success,
            "proxyIP": data.get("proxyIP", "-1"),
            "portRemote": data.get("portRemote", -1),
            "colo": data.get("colo", ""),
            "responseTime": data.get("responseTime", -1),
            "message": data.get("message", ""),
            "timestamp": data.get("timestamp", ""),
        }

        if success:
            log(
                f"✓ 可用 {ip}:443 "
                f"| {result['colo']} "
                f"| {result['responseTime']}ms"
            )
        else:
            log(
                f"✗ 不可用 {ip}:443 "
                f"| {result['message']}"
            )

        return result

    except Exception as e:
        log(f"✗ 检测失败 {ip}:443 | {e}")
        return {
            "ip": ip,
            "port": 443,
            "success": False,
            "error": str(e),
        }


# ============================================================
# 第四步：并发检测，找到3个有效IP后停止
# ============================================================

def find_valid_ips(ips, count=3):
    log("=" * 60)
    log(f"开始检测 {len(ips)} 个IP")
    log(f"目标：找到 {count} 个可用IP")
    log(f"并发数：{MAX_WORKERS}")
    log("=" * 60)

    valid_ips = []
    valid_results = []

    stop_event.clear()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

        future_to_ip = {
            executor.submit(check_proxy, ip): ip
            for ip in ips
        }

        for future in as_completed(future_to_ip):

            if len(valid_ips) >= count:
                break

            try:
                result = future.result()
            except Exception as e:
                ip = future_to_ip[future]
                log(f"任务异常 {ip}: {e}")
                continue

            if not result:
                continue

            if result.get("success"):

                ip = result["ip"]

                # 防止重复
                if ip not in valid_ips:
                    valid_ips.append(ip)
                    valid_results.append(result)

                    log(
                        f"★ 找到有效IP "
                        f"{len(valid_ips)}/{count}: {ip}:443"
                    )

                    # 达到目标
                    if len(valid_ips) >= count:
                        stop_event.set()
                        log("★ 已找到3个有效IP，停止继续寻找")

                        # 取消还没有开始执行的任务
                        for f in future_to_ip:
                            if not f.done():
                                f.cancel()

                        break

    if len(valid_ips) < count:
        log(
            f"⚠️ 有效IP不足："
            f"只找到 {len(valid_ips)}/{count} 个"
        )
        return valid_ips, valid_results

    log("=" * 60)
    log("最终有效IP：")
    for i, result in enumerate(valid_results, 1):
        log(
            f"{i}. {result['ip']}:443 "
            f"| {result.get('colo', '')} "
            f"| {result.get('responseTime', -1)}ms"
        )

    log("=" * 60)

    return valid_ips, valid_results


# ============================================================
# Cloudflare：获取DNS记录
# ============================================================

def get_existing_dns_records(zone_id):
    url = (
        f"https://api.cloudflare.com/client/v4/"
        f"zones/{zone_id}/dns_records"
    )

    response = session.get(
        url,
        headers=cf_headers,
        params={
            "type": "A",
            "per_page": 100,
        },
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        raise RuntimeError(
            f"Cloudflare获取DNS记录失败: {data}"
        )

    time.sleep(CF_DELAY)

    return data.get("result", [])


# ============================================================
# Cloudflare：删除DNS记录
# ============================================================

def delete_dns_record(zone_id, record_id, ip):
    url = (
        f"https://api.cloudflare.com/client/v4/"
        f"zones/{zone_id}/dns_records/{record_id}"
    )

    response = session.delete(
        url,
        headers=cf_headers,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        raise RuntimeError(
            f"Cloudflare删除失败 {ip}: {data}"
        )

    log(f"[Zone {zone_id}] 删除旧IP: {ip}")

    time.sleep(CF_DELAY)


# ============================================================
# Cloudflare：创建DNS记录
# ============================================================

def create_dns_record(zone_id, ip):
    url = (
        f"https://api.cloudflare.com/client/v4/"
        f"zones/{zone_id}/dns_records"
    )

    data = {
        "type": "A",
        "name": RECORD_NAME,
        "content": ip,
        "ttl": 60,
        "proxied": False,
    }

    response = session.post(
        url,
        headers=cf_headers,
        json=data,
        timeout=20,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("success"):
        raise RuntimeError(
            f"Cloudflare创建失败 {ip}: {result}"
        )

    log(f"[Zone {zone_id}] 新增IP: {ip}")

    time.sleep(CF_DELAY)


# ============================================================
# Cloudflare：差异更新
#
# 目标：
# 每个Zone最终都只有：
#
# yx1 -> IP1
# yx1 -> IP2
# yx1 -> IP3
# ============================================================

def diff_update_dns(zone_id, desired_ips):

    log("=" * 60)
    log(f"[Zone {zone_id}] 开始更新 DNS")
    log(f"[Zone {zone_id}] 目标IP: {desired_ips}")

    records = get_existing_dns_records(zone_id)

    existing = {}

    for record in records:

        if record.get("type") != "A":
            continue

        name = record.get("name", "")

        # 精确匹配：
        # yx1.example.com
        # 或者 yx1
        #
        # 原代码使用 split(".")[0]，
        # 这里保持兼容你的原逻辑。
        if name.split(".")[0].lower() != RECORD_NAME.lower():
            continue

        record_id = record.get("id")
        content = record.get("content")

        if record_id and content:
            existing[content] = record_id

    existing_ips = set(existing.keys())
    desired_ips = set(desired_ips)

    log(f"[Zone {zone_id}] 当前IP: {list(existing_ips)}")
    log(f"[Zone {zone_id}] 目标IP: {list(desired_ips)}")

    # 需要删除
    to_delete = existing_ips - desired_ips

    # 需要增加
    to_add = desired_ips - existing_ips

    # 已经存在
    keep = existing_ips & desired_ips

    # --------------------------------------------------------
    # 删除旧IP
    # --------------------------------------------------------

    for ip in to_delete:
        delete_dns_record(
            zone_id,
            existing[ip],
            ip
        )

    # --------------------------------------------------------
    # 添加新IP
    # --------------------------------------------------------

    for ip in to_add:
        create_dns_record(
            zone_id,
            ip
        )

    log(f"[Zone {zone_id}] 保留: {list(keep)}")
    log(f"[Zone {zone_id}] 删除: {list(to_delete)}")
    log(f"[Zone {zone_id}] 新增: {list(to_add)}")

    log(f"[Zone {zone_id}] DNS更新完成")


# ============================================================
# 主流程
# ============================================================

def main():

    log("=" * 60)
    log("程序开始")
    log("=" * 60)

    try:

        # ----------------------------------------------------
        # 1. 检查配置
        # ----------------------------------------------------

        zone_ids = check_config()

        log(f"Cloudflare Zone数量: {len(zone_ids)}")

        # ----------------------------------------------------
        # 2. 下载IP列表
        # ----------------------------------------------------

        text = fetch_source()

        # ----------------------------------------------------
        # 3. 提取443端口
        # ----------------------------------------------------

        ips = extract_443_ips(text)

        if not ips:
            log("❌ 没有找到443端口IP")
            return

        # ----------------------------------------------------
        # 4. 检测IP
        # ----------------------------------------------------

        valid_ips, valid_results = find_valid_ips(
            ips,
            VALID_IP_COUNT
        )

        # ----------------------------------------------------
        # 5. 必须找到3个才更新DNS
        #
        # 防止只有1~2个有效IP时把原来的DNS删掉
        # ----------------------------------------------------

        if len(valid_ips) < VALID_IP_COUNT:
            log(
                f"❌ 有效IP不足3个，"
                f"当前只有 {len(valid_ips)} 个"
            )
            log("❌ 为避免DNS被错误更新，本次不修改任何Zone")
            return

        # ----------------------------------------------------
        # 6. 更新所有Zone
        # ----------------------------------------------------

        log("=" * 60)
        log("开始更新所有Cloudflare Zone")
        log(f"统一目标IP: {valid_ips}")
        log("=" * 60)

        for index, zone_id in enumerate(zone_ids, 1):

            try:
                log(
                    f"处理 Zone "
                    f"{index}/{len(zone_ids)}: {zone_id}"
                )

                diff_update_dns(
                    zone_id,
                    valid_ips
                )

            except Exception as e:
                log(
                    f"❌ Zone {zone_id} 更新失败: {e}"
                )

        # ----------------------------------------------------
        # 7. 完成
        # ----------------------------------------------------

        log("=" * 60)
        log("全部处理完成")
        log(f"最终使用IP: {valid_ips}")
        log(f"更新Zone数量: {len(zone_ids)}")
        log("=" * 60)

    except Exception as e:

        log("=" * 60)
        log(f"❌ 程序异常: {e}")
        log("=" * 60)


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":
    main()
