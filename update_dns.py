import os
import csv
import time
import datetime
import requests


# ============================================================
# 配置
# ============================================================

RECORD_NAME = "yx1"

FINAL_IP_COUNT = 3

RESULT_FILE = "result.csv"

CF_DELAY = 1.2

CF_API_TOKEN = os.environ.get(
    "CLOUDFLARE_API_TOKEN"
)

CF_ZONE_ID_ENV = os.environ.get(
    "CF_ZONE_ID"
)


# ============================================================
# Session
# ============================================================

session = requests.Session()

cf_headers = {
    "Authorization":
        f"Bearer {CF_API_TOKEN}",

    "Content-Type":
        "application/json",
}


# ============================================================
# 日志
# ============================================================

def log(msg):

    now = datetime.datetime.now().strftime(
        "%H:%M:%S"
    )

    print(
        f"[{now}] {msg}",
        flush=True
    )


# ============================================================
# 配置检查
# ============================================================

def check_config():

    if not CF_API_TOKEN:

        raise ValueError(
            "缺少环境变量 "
            "CLOUDFLARE_API_TOKEN"
        )

    if not CF_ZONE_ID_ENV:

        raise ValueError(
            "缺少环境变量 CF_ZONE_ID"
        )

    zone_ids = [
        zone.strip()
        for zone in CF_ZONE_ID_ENV.split(",")
        if zone.strip()
    ]

    if not zone_ids:

        raise ValueError(
            "CF_ZONE_ID 没有有效的 Zone ID"
        )

    return zone_ids


# ============================================================
# 读取 CloudflareST result.csv
# ============================================================

def read_speedtest_result():

    if not os.path.exists(
        RESULT_FILE
    ):

        raise FileNotFoundError(
            f"找不到 {RESULT_FILE}"
        )

    log(
        f"读取测速结果: "
        f"{RESULT_FILE}"
    )

    results = []

    with open(
        RESULT_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.reader(f)

        rows = list(reader)

    if len(rows) < 2:

        raise RuntimeError(
            "CloudflareST 没有有效测速结果"
        )

    log(
        f"测速结果共 "
        f"{len(rows) - 1} 条"
    )

    for row in rows[1:]:

        if not row:
            continue

        # CloudflareST 标准 CSV：
        #
        # IP 地址
        # 已发送
        # 已接收
        # 丢包率
        # 平均延迟
        # 下载速度(MB/s)
        # 地区码

        if len(row) < 6:

            continue

        try:

            ip = row[0].strip()

            loss = float(
                row[3].strip()
            )

            latency = float(
                row[4].strip()
            )

            speed = float(
                row[5].strip()
            )

            colo = ""

            if len(row) >= 7:

                colo = row[6].strip()

            if not ip:

                continue

            results.append({
                "ip": ip,
                "loss": loss,
                "latency": latency,
                "speed": speed,
                "colo": colo,
            })

        except Exception as e:

            log(
                f"⚠ 跳过无效测速结果: "
                f"{row} | {e}"
            )

    if not results:

        raise RuntimeError(
            "CloudflareST 结果为空"
        )

    # --------------------------------------------------------
    # 按下载速度从高到低
    # --------------------------------------------------------

    results.sort(
        key=lambda x: x["speed"],
        reverse=True
    )

    return results


# ============================================================
# 选择最快3个
# ============================================================

def select_fastest(results):

    log("=" * 70)
    log("CloudflareST 下载速度排名")
    log("=" * 70)

    for index, result in enumerate(
        results,
        1
    ):

        log(
            f"{index:03d}. "
            f"{result['ip']}:443 "
            f"| "
            f"{result['speed']:.2f} MB/s "
            f"| 延迟 "
            f"{result['latency']:.2f}ms "
            f"| 丢包 "
            f"{result['loss']:.2f}% "
            f"| {result['colo']}"
        )

    if len(results) < FINAL_IP_COUNT:

        raise RuntimeError(
            f"有效测速结果只有 "
            f"{len(results)} 个，"
            f"不足 {FINAL_IP_COUNT} 个"
        )

    selected = results[
        :FINAL_IP_COUNT
    ]

    ips = [
        item["ip"]
        for item in selected
    ]

    log("=" * 70)
    log(
        f"最终最快 {FINAL_IP_COUNT} 个 IP"
    )
    log("=" * 70)

    for index, result in enumerate(
        selected,
        1
    ):

        log(
            f"{index}. "
            f"{result['ip']}:443 "
            f"| "
            f"{result['speed']:.2f} MB/s "
            f"| "
            f"{result['latency']:.2f}ms "
            f"| "
            f"{result['colo']}"
        )

    log("=" * 70)

    return ips


# ============================================================
# 获取 DNS 记录
# ============================================================

def get_existing_dns_records(
    zone_id
):

    url = (
        "https://api.cloudflare.com/client/v4/"
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
            f"Cloudflare获取DNS失败: "
            f"{data}"
        )

    time.sleep(
        CF_DELAY
    )

    return data.get(
        "result",
        []
    )


# ============================================================
# 删除 DNS
# ============================================================

def delete_dns_record(
    zone_id,
    record_id,
    ip
):

    url = (
        "https://api.cloudflare.com/client/v4/"
        f"zones/{zone_id}/dns_records/"
        f"{record_id}"
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
            f"Cloudflare删除失败 "
            f"{ip}: {data}"
        )

    log(
        f"[Zone {zone_id}] "
        f"删除旧IP: {ip}"
    )

    time.sleep(
        CF_DELAY
    )


# ============================================================
# 创建 DNS
# ============================================================

def create_dns_record(
    zone_id,
    ip
):

    url = (
        "https://api.cloudflare.com/client/v4/"
        f"zones/{zone_id}/dns_records"
    )

    payload = {
        "type": "A",
        "name": RECORD_NAME,
        "content": ip,
        "ttl": 60,
        "proxied": False,
    }

    response = session.post(
        url,
        headers=cf_headers,
        json=payload,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):

        raise RuntimeError(
            f"Cloudflare创建失败 "
            f"{ip}: {data}"
        )

    log(
        f"[Zone {zone_id}] "
        f"新增IP: {ip}"
    )

    time.sleep(
        CF_DELAY
    )


# ============================================================
# 更新单个 Zone
# ============================================================

def update_zone(
    zone_id,
    desired_ips
):

    log("=" * 70)
    log(
        f"[Zone {zone_id}] 开始更新"
    )

    log(
        f"[Zone {zone_id}] "
        f"目标IP: {desired_ips}"
    )

    records = get_existing_dns_records(
        zone_id
    )

    existing = {}

    for record in records:

        if record.get("type") != "A":

            continue

        name = record.get(
            "name",
            ""
        )

        # 匹配：
        #
        # yx1.example.com
        #
        # 或：
        #
        # yx1

        if (
            name.split(".")[0].lower()
            != RECORD_NAME.lower()
        ):

            continue

        record_id = record.get("id")
        content = record.get("content")

        if record_id and content:

            existing[
                content
            ] = record_id

    existing_ips = set(
        existing.keys()
    )

    desired_ips = set(
        desired_ips
    )

    to_delete = (
        existing_ips - desired_ips
    )

    to_add = (
        desired_ips - existing_ips
    )

    keep = (
        existing_ips & desired_ips
    )

    log(
        f"[Zone {zone_id}] "
        f"当前IP: {list(existing_ips)}"
    )

    log(
        f"[Zone {zone_id}] "
        f"保留: {list(keep)}"
    )

    log(
        f"[Zone {zone_id}] "
        f"删除: {list(to_delete)}"
    )

    log(
        f"[Zone {zone_id}] "
        f"新增: {list(to_add)}"
    )

    # --------------------------------------------------------
    # 删除旧 IP
    # --------------------------------------------------------

    for ip in to_delete:

        delete_dns_record(
            zone_id,
            existing[ip],
            ip
        )

    # --------------------------------------------------------
    # 添加新 IP
    # --------------------------------------------------------

    for ip in to_add:

        create_dns_record(
            zone_id,
            ip
        )

    log(
        f"[Zone {zone_id}] "
        f"DNS更新完成"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    log("=" * 70)
    log("开始处理 CloudflareST 测速结果")
    log("=" * 70)

    zone_ids = check_config()

    # --------------------------------------------------------
    # 1. 读取测速结果
    # --------------------------------------------------------

    results = read_speedtest_result()

    # --------------------------------------------------------
    # 2. 选择最快3个
    # --------------------------------------------------------

    fastest_ips = select_fastest(
        results
    )

    # --------------------------------------------------------
    # 3. 更新所有 Zone
    # --------------------------------------------------------

    log("=" * 70)
    log("开始更新所有 Cloudflare Zone")
    log(
        f"统一目标IP: {fastest_ips}"
    )
    log(
        f"Zone数量: {len(zone_ids)}"
    )
    log("=" * 70)

    failed_zones = []

    for index, zone_id in enumerate(
        zone_ids,
        1
    ):

        log(
            f"处理 Zone "
            f"{index}/{len(zone_ids)}: "
            f"{zone_id}"
        )

        try:

            update_zone(
                zone_id,
                fastest_ips
            )

        except Exception as e:

            log(
                f"❌ Zone {zone_id} "
                f"更新失败: {e}"
            )

            failed_zones.append(
                zone_id
            )

    # --------------------------------------------------------
    # 4. 最终结果
    # --------------------------------------------------------

    log("=" * 70)

    if failed_zones:

        log(
            f"❌ 部分 Zone 更新失败: "
            f"{failed_zones}"
        )

        raise RuntimeError(
            f"Zone更新失败: "
            f"{failed_zones}"
        )

    log(
        "✓ 所有 Zone 更新成功"
    )

    log(
        f"最终IP: {fastest_ips}"
    )

    log("=" * 70)


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        log(
            f"❌ 程序失败: {e}"
        )

        raise
