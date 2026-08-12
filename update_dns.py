import os
import csv
import time
import datetime
import requests


# ============================================================
# 配置
# ============================================================

RECORD_NAME = "yx2"

FINAL_IP_COUNT = 10

RESULT_FILE = "result.csv"

CF_DELAY = 1.2


# ============================================================
# Cloudflare 环境变量
#
# 只使用这两个环境变量：
#
# CLOUDFLARE_API_TOKEN
# CF_ZONE_ID
#
# CF_ZONE_ID 填写三个独立 Zone ID：
#
# CF_ZONE_ID=ZONE_ID_1,ZONE_ID_2,ZONE_ID_3
#
# 顺序对应：
#
# 第1个 Zone -> 第1名 IP
# 第2个 Zone -> 第2名 IP
# 第3个 Zone -> 第3名 IP
# ============================================================

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

    # --------------------------------------------------------
    # API Token
    # --------------------------------------------------------

    if not CF_API_TOKEN:

        raise ValueError(
            "缺少环境变量 "
            "CLOUDFLARE_API_TOKEN"
        )

    # --------------------------------------------------------
    # Zone ID
    # --------------------------------------------------------

    if not CF_ZONE_ID_ENV:

        raise ValueError(
            "缺少环境变量 "
            "CF_ZONE_ID"
        )

    zone_ids = [
        zone.strip()
        for zone in CF_ZONE_ID_ENV.split(",")
        if zone.strip()
    ]

    # --------------------------------------------------------
    # 必须正好三个 Zone
    # --------------------------------------------------------

    if len(zone_ids) != FINAL_IP_COUNT:

        raise ValueError(
            f"CF_ZONE_ID 必须包含 "
            f"{FINAL_IP_COUNT} 个 Zone ID，"
            f"当前检测到 "
            f"{len(zone_ids)} 个"
        )

    return zone_ids


# ============================================================
# 获取 Zone 信息
#
# 通过 Zone ID 自动获取真实域名
#
# GET /zones/{zone_id}
# ============================================================

def get_zone_info(
    zone_id
):

    url = (
        "https://api.cloudflare.com/client/v4/"
        f"zones/{zone_id}"
    )

    response = session.get(
        url,
        headers=cf_headers,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):

        raise RuntimeError(
            f"获取 Zone 信息失败 "
            f"{zone_id}: {data}"
        )

    result = data.get(
        "result"
    )

    if not result:

        raise RuntimeError(
            f"Cloudflare 返回的 Zone 信息为空: "
            f"{zone_id}"
        )

    zone_name = result.get(
        "name"
    )

    if not zone_name:

        raise RuntimeError(
            f"无法从 Zone ID 获取域名: "
            f"{zone_id}"
        )

    time.sleep(
        CF_DELAY
    )

    return zone_name


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

            # Cloudflare 单页最多100条
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

        # ----------------------------------------------------
        # CloudflareST 标准 CSV：
        #
        # IP 地址
        # 已发送
        # 已接收
        # 丢包率
        # 平均延迟
        # 下载速度(MB/s)
        # 地区码
        # ----------------------------------------------------

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

def select_fastest(
    results
):

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
            f"第 {index} 名: "
            f"{result['ip']}:443 "
            f"| "
            f"{result['speed']:.2f} MB/s "
            f"| "
            f"{result['latency']:.2f}ms "
            f"| "
            f"{result['colo']}"
        )

    log("=" * 70)

    return [
        result["ip"]
        for result in selected
    ]


# ============================================================
# 删除 DNS
# ============================================================

def delete_dns_record(
    zone_id,
    record_id,
    ip,
    fqdn
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
    ip,
    fqdn
):

    url = (
        "https://api.cloudflare.com/client/v4/"
        f"zones/{zone_id}/dns_records"
    )

    payload = {
        "type": "A",

        # ----------------------------------------------------
        # Zone 已经由 zone_id 确定
        #
        # 这里只填写主机记录：
        #
        # yx1
        #
        # Cloudflare 最终对应：
        #
        # yx1.example.com
        # ----------------------------------------------------

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
            f"{fqdn} -> {ip}: {data}"
        )

    log(
       
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
    domain,
    desired_ip
):

    fqdn = (
        f"{RECORD_NAME}.{domain}"
    )

    log("=" * 70)

    log(
        f"[Zone {zone_id}] "
        f"开始更新"
    )

    log(
        f"域名"
    )

    log(
        f"目标IP: {desired_ip}"
    )

    # --------------------------------------------------------
    # 获取当前 A 记录
    # --------------------------------------------------------

    records = get_existing_dns_records(
        zone_id
    )

    existing = []

    # --------------------------------------------------------
    # 精确匹配 yx1.domain
    #
    # 不会影响：
    #
    # domain
    # www.domain
    # yx2.domain
    # api.domain
    # --------------------------------------------------------

    for record in records:

        if record.get("type") != "A":

            continue

        name = record.get(
            "name",
            ""
        ).strip().lower()

        if name != fqdn.lower():

            continue

        record_id = record.get(
            "id"
        )

        content = record.get(
            "content"
        )

        if record_id and content:

            existing.append({
                "id": record_id,
                "ip": content,
            })

    existing_ips = [
        item["ip"]
        for item in existing
    ]

    log(
       
        f"当前IP: {existing_ips}"
    )

    # --------------------------------------------------------
    # 判断目标 IP 是否已经存在
    # --------------------------------------------------------

    target_exists = any(
        item["ip"] == desired_ip
        for item in existing
    )

    # --------------------------------------------------------
    # 删除旧 IP
    #
    # 如果存在多个 A 记录：
    #
    # 只保留目标 IP
    # 其他全部删除
    # --------------------------------------------------------

    for item in existing:

        if item["ip"] == desired_ip:

            continue

        delete_dns_record(
            zone_id,
            item["id"],
            item["ip"],
            fqdn
        )

    # --------------------------------------------------------
    # 添加目标 IP
    # --------------------------------------------------------

    if not target_exists:

        create_dns_record(
            zone_id,
            desired_ip,
            fqdn
        )

    else:

        log(
            
            f"目标IP已经存在，无需创建: "
            f"{desired_ip}"
        )

    log(
        
        f"DNS更新完成"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    log("=" * 70)
    log(
        "开始处理 CloudflareST 测速结果"
    )
    log("=" * 70)

    # ========================================================
    # 1. 检查配置
    # ========================================================

    zone_ids = check_config()

    log(
        f"检测到 {len(zone_ids)} 个 Cloudflare Zone"
    )

    # ========================================================
    # 2. 自动获取三个 Zone 的域名
    # ========================================================

    zone_domains = []

    log("=" * 70)
    log("获取 Cloudflare Zone 域名")
    log("=" * 70)

    for index, zone_id in enumerate(
        zone_ids,
        1
    ):

        log(
            f"正在获取 Zone "
            f"{index}/{len(zone_ids)}: "
            f"{zone_id}"
        )

        domain = get_zone_info(
            zone_id
        )

        zone_domains.append(
            domain
        )

        log(
            f"Zone {zone_id} "
           
        )

    log("=" * 70)

    # ========================================================
    # 3. 读取测速结果
    # ========================================================

    results = read_speedtest_result()

    # ========================================================
    # 4. 选择最快3个 IP
    # ========================================================

    fastest_ips = select_fastest(
        results
    )

    # ========================================================
    # 5. 建立对应关系
    #
    # 第1名 IP -> 第1个 Zone
    # 第2名 IP -> 第2个 Zone
    # 第3名 IP -> 第3个 Zone
    # ========================================================

    log("=" * 70)
    log("最终 IP -> 域名映射")
    log("=" * 70)

    for index in range(
        FINAL_IP_COUNT
    ):

        ip = fastest_ips[index]

        domain = zone_domains[index]

        fqdn = (
            f"{RECORD_NAME}.{domain}"
        )

        log(
            f"第 {index + 1} 名 IP: "
            f"{ip} "
            f"-> "
            f"{zone_id}"
        )

    log("=" * 70)

    # ========================================================
    # 6. 更新三个独立 Zone
    # ========================================================

    failed_zones = []

    for index in range(
        FINAL_IP_COUNT
    ):

        zone_id = zone_ids[index]

        domain = zone_domains[index]

        ip = fastest_ips[index]

        fqdn = (
            f"{RECORD_NAME}.{domain}"
        )

        log(
            f"处理 "
            f"{index + 1}/"
            f"{FINAL_IP_COUNT}: "
            f"{zone_id} "
            f"-> "
            f"{ip}"
        )

        try:

            update_zone(
                zone_id,
                domain,
                ip
            )

        except Exception as e:

            log(
                f"❌ Zone {zone_id} "
                f"({domain}) "
                f"更新失败: {e}"
            )

            failed_zones.append({
                "zone_id": zone_id,
                "domain": domain,
            })

    # ========================================================
    # 7. 最终结果
    # ========================================================

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

    log("=" * 70)

    for index in range(
        FINAL_IP_COUNT
    ):

        log(
            f"最终结果: 
            f"-> "
            f"{fastest_ips[index]}"
        )

    log("=" * 70)


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        log(
            f"❌ 程序失败: {e}"
        )

        raise
