import os
import time
import threading
import datetime
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode


# ============================================================
# 配置
# ============================================================

# IP 源地址
SOURCE_URL = os.environ.get("SOURCE_URL")

# ============================================================
# 新版 CF-Workers-CheckProxyIP API
#
# 示例：
# https://xxxxx.workers.dev
#
# 实际请求：
# /check?proxyip=1.2.3.4:443
# ============================================================

CHECK_API_URL = os.environ.get("CHECK_API_URL")


# ============================================================
# 本次最多验证多少个 IP
#
# 300 = 只验证前 300 个
#
# 如果设置为 0：
# 表示验证全部 IP
# ============================================================

CHECK_LIMIT = 0


# ============================================================
# API 并发数
#
# 免费 Worker 推荐从 32 开始
# ============================================================

API_MAX_WORKERS = 32


# ============================================================
# API 超时
# ============================================================

API_TIMEOUT = 15


# ============================================================
# API 失败重试次数
#
# 2 = 第一次失败后重试
#     第二次失败后再次重试
#
# 总请求次数最多 3 次
# ============================================================

API_RETRIES = 2


# ============================================================
# 重试基础间隔
# ============================================================

API_RETRY_DELAY = 1.5


# ============================================================
# 输出文件
# ============================================================

OUTPUT_FILE = "ip.txt"


# ============================================================
# Thread Local Session
#
# 每个线程使用自己的 requests.Session
# ============================================================

thread_local = threading.local()


def get_session():

    if not hasattr(
        thread_local,
        "session"
    ):

        session = requests.Session()

        session.headers.update({
            "User-Agent": (
                "CF-Workers-CheckProxyIP/"
                "BatchChecker/1.0"
            )
        })

        thread_local.session = session

    return thread_local.session


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
# 检查配置
# ============================================================

def check_config():

    if not SOURCE_URL:

        raise ValueError(
            "缺少环境变量 SOURCE_URL"
        )

    if not CHECK_API_URL:

        raise ValueError(
            "缺少环境变量 CHECK_API_URL"
        )


# ============================================================
# 下载 IP 列表
# ============================================================

def fetch_source():

    log(
        f"下载 IP 列表: {SOURCE_URL}"
    )

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
# 提取 443 IP
#
# 支持：
#
# 103.25.100.129:443
#
# 103.25.100.129:443#837-日本
#
# 最终只返回：
#
# 103.25.100.129
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

            # ------------------------------------------------
            # 去掉 # 后面的备注
            # ------------------------------------------------

            ip_port = line.split(
                "#",
                1
            )[0].strip()

            # ------------------------------------------------
            # 从最后一个 : 分割
            #
            # 例如：
            #
            # 1.2.3.4:443
            #
            # 如果以后出现 IPv6：
            #
            # [2001:db8::1]:443
            # ------------------------------------------------

            if ip_port.startswith("["):

                # IPv6：
                # [2001:db8::1]:443

                end_bracket = ip_port.rfind(
                    "]"
                )

                if end_bracket == -1:
                    raise ValueError(
                        "IPv6 格式错误"
                    )

                ip = ip_port[
                    1:end_bracket
                ]

                port = ip_port[
                    end_bracket + 1:
                ].lstrip(":")

            else:

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

    # --------------------------------------------------------
    # 去重，同时保持原始顺序
    # --------------------------------------------------------

    ips = list(
        dict.fromkeys(
            ips
        )
    )

    log(
        f"提取到 {len(ips)} 个 443 IP"
    )

    return ips


# ============================================================
# 构造新版 Worker API URL
#
# 新版：
#
# /check?proxyip=1.2.3.4:443
#
# 注意：
#
# 已经删除 token
# ============================================================

def build_api_url(ip):

    params = {
        "proxyip": f"{ip}:443"
    }

    return (
        f"{CHECK_API_URL.rstrip('/')}"
        f"/check?"
        f"{urlencode(params)}"
    )


# ============================================================
# API 检测单个 IP
# ============================================================

def check_proxy(ip):

    session = get_session()

    api_url = build_api_url(ip)

    for attempt in range(
        API_RETRIES + 1
    ):

        try:

            response = session.get(
                api_url,
                timeout=API_TIMEOUT
            )

            status = response.status_code

            # =================================================
            # 临时错误
            # =================================================

            if status in (
                429,
                500,
                502,
                503,
                504,
            ):

                if attempt < API_RETRIES:

                    log(
                        f"⚠ {ip}:443 "
                        f"HTTP {status} "
                        f"→ 重试 "
                        f"{attempt + 1}/"
                        f"{API_RETRIES}"
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

            # =================================================
            # 401 / 403
            #
            # 新版 Worker 已经没有 token。
            # 如果出现这些状态，一般不是 IP 本身的问题。
            # =================================================

            if status in (
                401,
                403,
            ):

                log(
                    f"✗ {ip}:443 "
                    f"HTTP {status}"
                )

                return None

            # =================================================
            # HTTP 错误
            # =================================================

            response.raise_for_status()

            # =================================================
            # JSON
            # =================================================

            data = response.json()

            # =================================================
            # success
            #
            # 新版 Worker 主要通过 success 判断。
            # =================================================

            success = data.get(
                "success",
                False
            )

            # =================================================
            # IP 验证成功
            # =================================================

            if success:

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

            # =================================================
            # API 正常返回，但 IP 不合格
            # =================================================

            return None

        # =====================================================
        # API 超时
        # =====================================================

        except requests.exceptions.Timeout:

            if attempt < API_RETRIES:

                log(
                    f"⚠ {ip}:443 "
                    f"API超时 "
                    f"→ 重试 "
                    f"{attempt + 1}/"
                    f"{API_RETRIES}"
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

        # =====================================================
        # requests 网络异常
        # =====================================================

        except requests.exceptions.RequestException as e:

            if attempt < API_RETRIES:

                log(
                    f"⚠ {ip}:443 "
                    f"请求异常 "
                    f"→ 重试 "
                    f"{attempt + 1}/"
                    f"{API_RETRIES}"
                    f" | {e}"
                )

                time.sleep(
                    API_RETRY_DELAY
                    * (attempt + 1)
                )

                continue

            log(
                f"✗ {ip}:443 "
                f"API请求失败 | {e}"
            )

            return None

        # =====================================================
        # JSON 解析异常
        # =====================================================

        except ValueError as e:

            log(
                f"✗ {ip}:443 "
                f"API返回非JSON | {e}"
            )

            return None

        # =====================================================
        # 其他异常
        # =====================================================

        except Exception as e:

            log(
                f"✗ {ip}:443 "
                f"API异常 | {e}"
            )

            return None

    return None


# ============================================================
# 检测全部 IP
# ============================================================

def check_all_ips(ips):

    if not ips:

        return []


    # ========================================================
    # 只验证前 CHECK_LIMIT 个 IP
    #
    # CHECK_LIMIT = 300
    #
    # 如果 CHECK_LIMIT = 0：
    # 验证全部
    # ========================================================

    if CHECK_LIMIT > 0:

        check_ips = ips[
            :CHECK_LIMIT
        ]

    else:

        check_ips = ips


    log("=" * 70)

    log(
        "开始 API 并发检测"
    )

    log(
        f"源IP数量: {len(ips)}"
    )

    log(
        f"本次验证: {len(check_ips)}"
    )

    log(
        f"API并发数: {API_MAX_WORKERS}"
    )

    log(
        f"API超时: {API_TIMEOUT} 秒"
    )

    log(
        f"失败重试: {API_RETRIES} 次"
    )

    log("=" * 70)


    valid_ips = []

    completed = 0

    start_time = time.time()


    # ========================================================
    # ThreadPool
    # ========================================================

    with ThreadPoolExecutor(
        max_workers=API_MAX_WORKERS
    ) as executor:

        future_to_ip = {
            executor.submit(
                check_proxy,
                ip
            ): ip
            for ip in check_ips
        }


        # ====================================================
        # 按完成顺序获取结果
        # ====================================================

        for future in as_completed(
            future_to_ip
        ):

            ip = future_to_ip[
                future
            ]

            completed += 1

            try:

                result = future.result()

            except Exception as e:

                log(
                    f"✗ 任务异常 "
                    f"{ip}:443 | {e}"
                )

                continue


            # =================================================
            # 合格
            # =================================================

            if result:

                valid_ips.append(
                    result["ip"]
                )


            # =================================================
            # 进度
            # =================================================

            if (
                completed % 10 == 0
                or completed == len(check_ips)
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
                    f"{completed}/"
                    f"{len(check_ips)} "
                    f"| 合格 "
                    f"{len(valid_ips)} "
                    f"| "
                    f"{speed:.2f} IP/s"
                )


    # ========================================================
    # 最终去重
    # ========================================================

    valid_ips = list(
        dict.fromkeys(
            valid_ips
        )
    )


    elapsed = (
        time.time()
        - start_time
    )


    log("=" * 70)

    log(
        "API检测完成"
    )

    log(
        f"验证数量: {len(check_ips)}"
    )

    log(
        f"合格数量: {len(valid_ips)}"
    )

    log(
        f"耗时: {elapsed:.1f} 秒"
    )


    if elapsed > 0:

        log(
            f"平均速度: "
            f"{len(check_ips) / elapsed:.2f} IP/s"
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

    log(
        "开始准备 CloudflareST 测速"
    )

    log("=" * 70)


    # ========================================================
    # 1. 检查配置
    # ========================================================

    check_config()


    # ========================================================
    # 2. 下载 IP 列表
    # ========================================================

    text = fetch_source()


    # ========================================================
    # 3. 提取 443 IP
    # ========================================================

    ips = extract_443_ips(
        text
    )


    if not ips:

        raise RuntimeError(
            "没有找到任何 443 IP"
        )


    # ========================================================
    # 4. API 验证
    #
    # 默认只验证前 300 个
    # ========================================================

    valid_ips = check_all_ips(
        ips
    )


    # ========================================================
    # 5. 一个都没有通过
    # ========================================================

    if not valid_ips:

        raise RuntimeError(
            "没有任何 IP 通过 API 检测"
        )


    # ========================================================
    # 6. 输出 ip.txt
    # ========================================================

    write_ip_file(
        valid_ips
    )


    # ========================================================
    # 完成
    # ========================================================

    log("=" * 70)

    log(
        "准备完成"
    )

    log("=" * 70)


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        log(
            f"❌ 程序失败: {e}"
        )

        raise
