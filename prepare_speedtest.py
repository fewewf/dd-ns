import os
import time
import threading
import datetime
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 配置
# ============================================================

SOURCE_URL = "https://raw.githubusercontent.com/tiantuuy/test/refs/heads/main/jp.txt"

# API
CHECK_TOKEN = "zfwkn"
CHECK_API_URL = os.environ.get("CHECK_API_URL")

# API 并发数
API_MAX_WORKERS = 16

# API 超时
API_TIMEOUT = 15

# API 失败重试次数
API_RETRIES = 2

# 重试间隔
API_RETRY_DELAY = 1.5

# 输出文件
OUTPUT_FILE = "ip.txt"


# ============================================================
# Thread Local Session
# 每个线程使用独立 Session
# ============================================================

thread_local = threading.local()


def get_session():

    if not hasattr(thread_local, "session"):

        thread_local.session = requests.Session()

    return thread_local.session


# ============================================================
# 日志
# ============================================================

def log(msg):

    now = datetime.datetime.now().strftime("%H:%M:%S")

    print(
        f"[{now}] {msg}",
        flush=True
    )


# ============================================================
# 检查配置
# ============================================================

def check_config():

    if not CHECK_API_URL:

        raise ValueError(
            "缺少环境变量 CHECK_API_URL"
        )


# ============================================================
# 下载 IP 列表
# ============================================================

def fetch_source():

    #log(
       # f"下载IP列表: {SOURCE_URL}"
   # )

    session = requests.Session()

    response = session.get(
        SOURCE_URL,
        timeout=30
    )

    response.raise_for_status()

    lines = response.text.splitlines()

    log(
        f"IP列表下载成功，共 {len(lines)} 行"
    )

    return response.text


# ============================================================
# 提取所有 443 IP
#
# 示例：
#
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

            # 去掉 # 后面的备注
            ip_port = line.split(
                "#",
                1
            )[0].strip()

            # 最后一个 : 分割
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
                f"⚠ 跳过格式错误 "
                f"第 {line_num} 行: {line}"
            )

    # 去重，同时保持原始顺序
    ips = list(
        dict.fromkeys(ips)
    )

    log(
        f"提取到 {len(ips)} 个 443 IP"
    )

    return ips


# ============================================================
# API 检测单个 IP
# ============================================================

def check_proxy(ip):

    session = get_session()

    api_url = (
        f"{CHECK_API_URL.rstrip('/')}"
        f"/check"
        f"?proxyip={ip}:443"
        f"&token={CHECK_TOKEN}"
    )

    for attempt in range(
        API_RETRIES + 1
    ):

        try:

            response = session.get(
                api_url,
                timeout=API_TIMEOUT
            )

            status = response.status_code

            # ------------------------------------------------
            # Cloudflare / Worker / 上游常见临时错误
            # ------------------------------------------------

            if status in (
                502,
                503,
                504,
            ):

                if attempt < API_RETRIES:

                    log(
                        f"⚠ {ip}:443 "
                        f"HTTP {status} "
                        f"→ "
                        f"重试 {attempt + 1}/{API_RETRIES}"
                    )

                    time.sleep(
                        API_RETRY_DELAY
                        * (attempt + 1)
                    )

                    continue

                log(
                    f"✗ {ip}:443 "
                    f"HTTP {status}"
                )

                return None

            response.raise_for_status()

            data = response.json()

            success = data.get(
                "success",
                False
            )

            # ------------------------------------------------
            # API 检测成功
            # ------------------------------------------------

            if success:

               # log(
                  #  f"✓ 合格 {ip}:443 "
                  #  f"| {data.get('colo', '')} "
                   # f"| {data.get('responseTime', -1)}ms"
                #)

                return {
                    "ip": ip,
                    "success": True,
                    "colo": data.get(
                        "colo",
                        ""
                    ),
                    "responseTime": data.get(
                        "responseTime",
                        -1
                    ),
                }

            # ------------------------------------------------
            # API 正常返回，但是 IP 不合格
            # ------------------------------------------------

            #log(
                #f"✗ 不合格 {ip}:443 "
               # f"| {data.get('message', '')}"
           # )

            return None

        except requests.exceptions.Timeout:

            if attempt < API_RETRIES:

                log(
                    f"⚠ {ip}:443 "
                    f"API超时 "
                    f"→ 重试 "
                    f"{attempt + 1}/{API_RETRIES}"
                )

                time.sleep(
                    API_RETRY_DELAY
                    * (attempt + 1)
                )

                continue

            log(
                f"✗ {ip}:443 "
                f"API连续超时"
            )

            return None

        except requests.exceptions.RequestException as e:

            log(
                f"✗ {ip}:443 "
                f"API请求异常 | {e}"
            )

            return None

        except Exception as e:

            log(
                f"✗ {ip}:443 "
                f"API异常 | {e}"
            )

            return None

    return None


# ============================================================
# 并发 API 检测全部 IP
# ============================================================

def check_all_ips(ips):

    log("=" * 70)
    log("开始 API 并发检测")
    log(f"IP数量: {len(ips)}")
    log(f"并发数: {API_MAX_WORKERS}")
    log("=" * 70)

    valid_ips = []

    completed = 0

    start_time = time.time()

    with ThreadPoolExecutor(
        max_workers=API_MAX_WORKERS
    ) as executor:

        future_to_ip = {
            executor.submit(
                check_proxy,
                ip
            ): ip
            for ip in ips
        }

        for future in as_completed(
            future_to_ip
        ):

            ip = future_to_ip[future]

            completed += 1

            try:

                result = future.result()

            except Exception as e:

                log(
                    f"✗ 任务异常 "
                    f"{ip}:443 | {e}"
                )

                continue

            if result and result.get(
                "success"
            ):

                valid_ips.append(ip)

            # ------------------------------------------------
            # 进度
            # ------------------------------------------------

            if (
                completed % 10 == 0
                or completed == len(ips)
            ):

                elapsed = (
                    time.time()
                    - start_time
                )

                speed = (
                    completed / elapsed
                    if elapsed > 0
                    else 0
                )

                log(
                    f"进度 "
                    f"{completed}/{len(ips)} "
                    f"| 合格 "
                    f"{len(valid_ips)} "
                    f"| "
                    f"{speed:.2f} IP/s"
                )

    elapsed = (
        time.time()
        - start_time
    )

    log("=" * 70)
    log("API检测完成")
    log(f"总数: {len(ips)}")
    log(f"合格: {len(valid_ips)}")
    log(f"耗时: {elapsed:.1f} 秒")

    if elapsed > 0:

        log(
            f"平均速度: "
            f"{len(ips) / elapsed:.2f} IP/s"
        )

    log("=" * 70)

    return valid_ips


# ============================================================
# 写入 ip.txt
# ============================================================

def write_ip_file(ips):

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        for ip in ips:

            f.write(
                f"{ip}\n"
            )

    log(
        f"已生成 {OUTPUT_FILE}"
    )

    log(
        f"CloudflareST候选IP数量: "
        f"{len(ips)}"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    log("=" * 70)
    log("开始准备 CloudflareST 测速")
    log("=" * 70)

    check_config()

    # --------------------------------------------------------
    # 1. 下载 IP
    # --------------------------------------------------------

    text = fetch_source()

    # --------------------------------------------------------
    # 2. 提取 443
    # --------------------------------------------------------

    ips = extract_443_ips(text)

    if not ips:

        raise RuntimeError(
            "没有找到任何 443 IP"
        )

    # --------------------------------------------------------
    # 3. API 并发检测
    # --------------------------------------------------------

    valid_ips = check_all_ips(
        ips
    )

    # --------------------------------------------------------
    # 4. API 一个都没通过
    # --------------------------------------------------------

    if not valid_ips:

        raise RuntimeError(
            "没有任何 IP 通过 API 检测"
        )

    # --------------------------------------------------------
    # 5. 写入 CloudflareST
    # --------------------------------------------------------

    write_ip_file(
        valid_ips
    )

    log("=" * 70)
    log("准备完成")
    log("=" * 70)


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        log(
            f"❌ 程序失败: {e}"
        )

        raise
