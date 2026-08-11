import os
import requests
import datetime
import time
import csv
import sys

# ============================================================
# 配置
# ============================================================

SOURCE_URL = "https://ddx.snu.cc/JP"

# Cloudflare DNS
RECORD_NAME = "yx1"
CF_DELAY = 1.2

# API 检测
CHECK_TOKEN = "zfwkn"
CHECK_API_URL = os.environ.get("CHECK_API_URL")

# Cloudflare
CF_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
CF_ZONE_ID_ENV = os.environ.get("CF_ZONE_ID")

# CloudflareST 输出
RESULT_FILE = "result.csv"

# 最终使用多少个最快 IP
FINAL_IP_COUNT = 3


# ============================================================
# Session
# ============================================================

session = requests.Session()

cf_headers = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json",
}


# ============================================================
# 日志
# ============================================================

def log(msg):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# ============================================================
# 配置检查
# ============================================================

def check_config():

    if not CF_API_TOKEN:
        raise ValueError(
            "缺少环境变量 CLOUDFLARE_API_TOKEN"
        )

    if not CF_ZONE_ID_ENV:
        raise ValueError(
            "缺少环境变量 CF_ZONE_ID"
        )

    if not CHECK_API_URL:
        raise ValueError(
            "缺少环境变量 CHECK_API_URL"
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
# 下载 IP 列表
# ============================================================

def fetch_source():

    log(f"下载IP列表: {SOURCE_URL}")

    response = session.get(
        SOURCE_URL,
        timeout=20
    )

    response.raise_for_status()

    lines = response.text.splitlines()

    log(f"IP列表下载成功，共 {len(lines)} 行")

    return response.text


# ============================================================
# 提取所有 443 IP
#
# 示例：
# 103.25.100.129:443#837-日本
# ============================================================

def extract_443_ips(text):

    ips = []

    for line_num, line in enumerate(
        text.splitlines(),
        1
    ):

        line = line.strip()

        if not line:
            continue

        try:

            ip_port = line.split(
                "#",
                1
            )[0].strip()

            ip, port = ip_port.rsplit(
                ":",
                1
            )

            ip = ip.strip()
            port = port.strip()

            if port == "443":
                ips.append(ip)

        except Exception:

            log(
                f"跳过格式错误，第 {line_num} 行: {line}"
            )

    # 去重
    ips = list(
        dict.fromkeys(ips)
    )

    log(
        f"提取到 {len(ips)} 个443端口IP"
    )

    return ips


# ============================================================
# API 检测单个 IP
# ============================================================

def check_proxy(ip):

    api_url = (
        f"{CHECK_API_URL.rstrip('/')}"
        f"/check"
        f"?proxyip={ip}:443"
        f"&token={CHECK_TOKEN}"
    )

    try:

        response = session.get(
            api_url,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        success = data.get(
            "success",
            False
        )

        if success:

            log(
                f"✓ API合格 {ip}:443 "
                f"| {data.get('colo', '')} "
                f"| {data.get('responseTime', -1)}ms"
            )

            return True

        log(
            f"✗ API不合格 {ip}:443 "
            f"| {data.get('message', '')}"
        )

        return False

    except Exception as e:

        log(
            f"✗ API检测失败 {ip}:443 | {e}"
        )

        return False


# ============================================================
# API 检测全部 IP
#
# 注意：
# 这里故意不再找到3个就停止。
#
# 必须把所有 API 合格 IP 都交给 CloudflareST。
# ============================================================

def api_check_all(ips):

    log("=" * 60)
    log("开始 API 初筛")
    log(f"待检测IP: {len(ips)}")
    log("=" * 60)

    valid_ips = []

    for index, ip in enumerate(
        ips,
        1
    ):

        log(
            f"[{index}/{len(ips)}] "
            f"检测 {ip}:443"
        )

        if check_proxy(ip):

            valid_ips.append(ip)

    log("=" * 60)

    log(
        f"API检测完成："
        f"{len(valid_ips)}/{len(ips)} 个IP合格"
    )

    log("=" * 60)

    return valid_ips


# ============================================================
# 写入 CloudflareST 输入文件
# ============================================================

def write_speedtest_ips(ips):

    filename = "ip.txt"

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        for ip in ips:
            f.write(f"{ip}\n")

    log(
        f"已生成 CloudflareST 输入文件: "
        f"{filename}"
    )

    log(
        f"测速IP数量: {len(ips)}"
    )

    return filename


# ============================================================
# 读取 CloudflareST result.csv
#
# 格式：
#
# IP 地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s),地区码
#
# 例如：
# 104.27.200.69,4,4,0.00,146.23,28.64,LAX
# ============================================================

def read_speedtest_result():

    if not os.path.exists(
        RESULT_FILE
    ):

        raise FileNotFoundError(
            f"找不到 CloudflareST 结果文件: "
            f"{RESULT_FILE}"
        )

    log(
        f"读取 CloudflareST 结果: "
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
            "CloudflareST 没有产生有效测速结果"
        )

    header = rows[0]

    log(
        f"测速结果字段: {header}"
    )

    for row in rows[1:]:

        if not row:
            continue

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

            colo = (
                row[6].strip()
                if len(row) > 6
                else ""
            )

            results.append({
                "ip": ip,
                "loss": loss,
                "latency": latency,
                "speed": speed,
                "colo": colo,
            })

        except Exception as e:

            log(
                f"跳过无效测速结果: "
                f"{row} | {e}"
            )

    if not results:

        raise RuntimeError(
            "CloudflareST 结果为空"
        )

    # 按下载速度从高到低
    results.sort(
        key=lambda x: x["speed"],
        reverse=True
    )

    return results


# ============================================================
# 选择最快 3 个 IP
# ============================================================

def select_fastest_ips(results):

    log("=" * 60)
    log("CloudflareST 下载速度排名")
    log("=" * 60)

    for index, result in enumerate(
        results,
        1
    ):

        log(
            f"{index:02d}. "
            f"{result['ip']}:443 "
            f"| {result['speed']} MB/s "
            f"| 延迟 {result['latency']}ms "
            f"| 丢包 {result['loss']} "
            f"| {result['colo']}"
        )

    if len(results) < FINAL_IP_COUNT:

        raise RuntimeError(
            f"测速结果只有 {len(results)} 个，"
            f"不足 {FINAL_IP_COUNT} 个"
        )

    selected = results[
        :FINAL_IP_COUNT
    ]

    ips = [
        result["ip"]
        for result in selected
    ]

    log("=" * 60)
    log(
        f"最终选择最快 {FINAL_IP_COUNT} 个IP:"
    )

    for index, result in enumerate(
        selected,
        1
    ):

        log(
            f"{index}. "
            f"{result['ip']}:443 "
            f"| {result['speed']} MB/s "
            f"| {result['colo']}"
        )

    log("=" * 60)

    return ips


# ============================================================
# Cloudflare：获取 DNS 记录
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
            f"Cloudflare获取DNS记录失败: "
            f"{data}"
        )

    time.sleep(CF_DELAY)

    return data.get(
        "result",
        []
    )


# ============================================================
# Cloudflare：删除 DNS
# ============================================================

def delete_dns_record(
    zone_id,
    record_id,
    ip
):

    url = (
        "https://api.cloudflare.com/client/v4/"
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
            f"Cloudflare删除失败 {ip}: "
            f"{data}"
        )

    log(
        f"[Zone {zone_id}] 删除旧IP: {ip}"
    )

    time.sleep(CF_DELAY)


# ============================================================
# Cloudflare：创建 DNS
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

    result = response.json()

    if not result.get("success"):

        raise RuntimeError(
            f"Cloudflare创建失败 {ip}: "
            f"{result}"
        )

    log(
        f"[Zone {zone_id}] 新增IP: {ip}"
    )

    time.sleep(CF_DELAY)


# ============================================================
# Cloudflare DNS 差异更新
# ============================================================

def diff_update_dns(
    zone_id,
    desired_ips
):

    log("=" * 60)
    log(
        f"[Zone {zone_id}] 开始更新 DNS"
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

        # 例如：
        # yx1.example.com
        #
        # 也兼容：
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
        f"[Zone {zone_id}] 当前IP: "
        f"{list(existing_ips)}"
    )

    log(
        f"[Zone {zone_id}] 目标IP: "
        f"{list(desired_ips)}"
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
        f"[Zone {zone_id}] 保留: "
        f"{list(keep)}"
    )

    log(
        f"[Zone {zone_id}] 删除: "
        f"{list(to_delete)}"
    )

    log(
        f"[Zone {zone_id}] 新增: "
        f"{list(to_add)}"
    )

    log(
        f"[Zone {zone_id}] DNS更新完成"
    )


# ============================================================
# 主流程
# ============================================================

def main():

    log("=" * 60)
    log("Cloudflare IP 自动筛选开始")
    log("=" * 60)

    try:

        # ----------------------------------------------------
        # 1. 检查环境变量
        # ----------------------------------------------------

        zone_ids = check_config()

        log(
            f"Cloudflare Zone数量: "
            f"{len(zone_ids)}"
        )

        # ----------------------------------------------------
        # 2. 下载 IP
        # ----------------------------------------------------

        text = fetch_source()

        # ----------------------------------------------------
        # 3. 提取所有 443 IP
        # ----------------------------------------------------

        ips = extract_443_ips(text)

        if not ips:

            raise RuntimeError(
                "没有找到443端口IP"
            )

        # ----------------------------------------------------
        # 4. API 检测所有 IP
        # ----------------------------------------------------

        valid_ips = api_check_all(
            ips
        )

        if not valid_ips:

            raise RuntimeError(
                "没有任何 IP 通过 API 检测"
            )

        log(
            f"API合格IP数量: "
            f"{len(valid_ips)}"
        )

        # ----------------------------------------------------
        # 5. 写入 CloudflareST
        # ----------------------------------------------------

        write_speedtest_ips(
            valid_ips
        )

        # ----------------------------------------------------
        # 6. CloudflareST 已经在 GitHub Actions 中执行
        # ----------------------------------------------------
        #
        # 这里直接读取 result.csv
        # ----------------------------------------------------

        results = read_speedtest_result()

        # ----------------------------------------------------
        # 7. 按下载速度选择最快3个
        # ----------------------------------------------------

        fastest_ips = select_fastest_ips(
            results
        )

        # ----------------------------------------------------
        # 8. 更新所有 Zone
        # ----------------------------------------------------

        log("=" * 60)
        log("开始更新所有 Cloudflare Zone")
        log(
            f"统一目标IP: {fastest_ips}"
        )
        log("=" * 60)

        failed_zones = []

        for index, zone_id in enumerate(
            zone_ids,
            1
        ):

            try:

                log(
                    f"处理 Zone "
                    f"{index}/{len(zone_ids)}: "
                    f"{zone_id}"
                )

                diff_update_dns(
                    zone_id,
                    fastest_ips
                )

            except Exception as e:

                failed_zones.append(
                    zone_id
                )

                log(
                    f"❌ Zone {zone_id} "
                    f"更新失败: {e}"
                )

        # ----------------------------------------------------
        # 9. 最终结果
        # ----------------------------------------------------

        log("=" * 60)

        if failed_zones:

            log(
                f"⚠️ 部分 Zone 更新失败: "
                f"{failed_zones}"
            )

        else:

            log(
                "✓ 所有 Zone 更新成功"
            )

        log(
            f"最终IP: {fastest_ips}"
        )

        log("=" * 60)

        # 如果有 Zone 更新失败，让 GitHub Actions 失败
        if failed_zones:
            sys.exit(1)

    except Exception as e:

        log("=" * 60)
        log(
            f"❌ 程序异常: {e}"
        )
        log("=" * 60)

        sys.exit(1)


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":
    main()
