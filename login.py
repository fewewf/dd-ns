import os
import time
import requests

from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 配置
# ============================================================

# 下载代理列表
PROXY_FILE_URL = os.getenv("PROXY_FILE_URL")

# Cloudflare Worker API
CHECK_API_URL = os.getenv("CHECK_API_URL")

# 国家
TARGET_COUNTRY = os.getenv("TARGET_COUNTRY", "JP").strip().upper()

# 目标端口
TARGET_PORT = os.getenv("TARGET_PORT", "8443").strip()

# Worker 内部单阶段检测超时
WORKER_TIMEOUT_MS = int(
    os.getenv("WORKER_TIMEOUT_MS", "5000")
)

# Python 等待 Worker HTTP 响应的时间
REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "10")
)

# 最大并发数
MAX_WORKERS = int(
    os.getenv("MAX_WORKERS", "20")
)

# 最大允许延迟
MAX_RESPONSE_TIME = int(
    os.getenv("MAX_RESPONSE_TIME", "500")
)

# 每个 IP 最大重试次数
MAX_RETRIES = int(
    os.getenv("MAX_RETRIES", "2")
)

# 重试间隔
RETRY_DELAY = float(
    os.getenv("RETRY_DELAY", "0.5")
)

# 本地文件
LOCAL_FILENAME = "proxy_source.txt"
OUTPUT_FILENAME = "ip.txt"


# ============================================================
# Session
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 ProxyChecker/1.0"
})


# ============================================================
# 下载文件
# ============================================================

def download_file(url, filename):
    """
    下载代理文件
    """

    if not url:
        print("错误: PROXY_FILE_URL 未设置")
        return False

    try:

        response = session.get(
            url,
            timeout=30
        )

        response.raise_for_status()

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(response.text)

        print(
            f"文件下载成功: {filename} "
            f"({len(response.text)} bytes)"
        )

        return True

    except requests.RequestException as e:

        print(
            f"文件下载失败: {type(e).__name__}: {e}"
        )

        return False

    except Exception as e:

        print(
            f"文件下载失败: {type(e).__name__}: {e}"
        )

        return False


# ============================================================
# 提取指定国家 + 指定端口
# ============================================================

def extract_proxies(filename):
    """
    提取：

        IP:PORT#COUNTRY

    例如：

        1.2.3.4:8443#JP
    """

    proxies = []

    try:

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            for line_num, line in enumerate(f, 1):

                line = line.strip()

                if not line:
                    continue

                try:

                    # ------------------------------------------------
                    # 分割 #
                    # ------------------------------------------------

                    ip_port, country = line.split(
                        "#",
                        1
                    )

                    country = country.strip().upper()

                    # ------------------------------------------------
                    # 国家过滤
                    # ------------------------------------------------

                    if country != TARGET_COUNTRY:
                        continue

                    # ------------------------------------------------
                    # IPv4:PORT
                    # ------------------------------------------------

                    if ":" not in ip_port:
                        continue

                    ip, port = ip_port.rsplit(
                        ":",
                        1
                    )

                    ip = ip.strip()
                    port = port.strip()

                    # ------------------------------------------------
                    # 端口过滤
                    # ------------------------------------------------

                    if port != TARGET_PORT:
                        continue

                    if not ip:
                        continue

                    proxy_info = {
                        "ip": ip,
                        "port": port,
                        "full_line": line,
                        "line_num": line_num
                    }

                    proxies.append(proxy_info)

                except ValueError:

                    continue

        # ------------------------------------------------------------
        # 去重
        # ------------------------------------------------------------

        unique = {}

        for proxy in proxies:

            key = (
                proxy["ip"],
                proxy["port"]
            )

            if key not in unique:
                unique[key] = proxy

        proxies = list(unique.values())

        print(
            f"找到 {len(proxies)} 个 "
            f"{TARGET_COUNTRY} + {TARGET_PORT} 代理"
        )

        return proxies

    except Exception as e:

        print(
            f"读取文件失败: "
            f"{type(e).__name__}: {e}"
        )

        return []


# ============================================================
# 创建 Worker URL
# ============================================================

def build_check_url(api_base_url, ip, port):
    """
    构造：

    /check?proxyip=IP:PORT&timeoutMs=5000
    """

    api_base_url = api_base_url.rstrip("/")

    proxy_url = f"{ip}:{port}"

    params = {
        "proxyip": proxy_url,
        "timeoutMs": WORKER_TIMEOUT_MS
    }

    return (
        f"{api_base_url}/check?"
        f"{urlencode(params)}"
    )


# ============================================================
# 判断出口 IP 类型
# ============================================================

def detect_exit_ip_type(data):
    """
    根据 Worker 返回的 probe_results 判断出口 IP 类型。

    Worker 返回结构示例：

    {
        "probe_results": {
            "ipv4": {
                "ok": true,
                "exit": {
                    "ip": "198.51.100.20",
                    "ipType": "ipv4"
                }
            },
            "ipv6": {
                "ok": true,
                "exit": {
                    "ip": "2001:db8::1",
                    "ipType": "ipv6"
                }
            }
        }
    }

    返回：

        {
            "is_ipv4_exit": True,
            "is_ipv6_exit": False,
            "is_dual_stack_exit": False,
            "exit_ipv4": "198.51.100.20",
            "exit_ipv6": "",
            "exit_ip_type": "ipv4"
        }

    注意：
    1. 优先根据 probe_results 中实际出口 IP 判断。
    2. probe_results 缺失时，兼容 supports_ipv4 等字段。
    3. IPv4 和 IPv6 都存在时，判断为双栈。
    """

    probe_results = data.get(
        "probe_results",
        {}
    ) or {}

    # ------------------------------------------------------------
    # 提取 IPv4 探测结果
    # ------------------------------------------------------------

    ipv4_result = probe_results.get(
        "ipv4",
        {}
    ) or {}

    ipv4_exit = ipv4_result.get(
        "exit",
        {}
    ) or {}

    exit_ipv4 = ipv4_exit.get(
        "ip",
        ""
    )

    # ------------------------------------------------------------
    # 提取 IPv6 探测结果
    # ------------------------------------------------------------

    ipv6_result = probe_results.get(
        "ipv6",
        {}
    ) or {}

    ipv6_exit = ipv6_result.get(
        "exit",
        {}
    ) or {}

    exit_ipv6 = ipv6_exit.get(
        "ip",
        ""
    )

    # ------------------------------------------------------------
    # 优先依据实际探针出口 IP 判断
    # ------------------------------------------------------------

    is_ipv4_exit = bool(
        exit_ipv4
    )

    is_ipv6_exit = bool(
        exit_ipv6
    )

    # ------------------------------------------------------------
    # 兼容旧字段
    #
    # 仅在 probe_results 没有明确出口 IP 时使用
    # ------------------------------------------------------------

    if not is_ipv4_exit and not is_ipv6_exit:

        supports_ipv4 = data.get(
            "supports_ipv4",
            False
        ) is True

        supports_ipv6 = data.get(
            "supports_ipv6",
            False
        ) is True

        inferred_stack = str(
            data.get(
                "inferred_stack",
                ""
            )
        ).lower()

        # 根据辅助字段推断
        if supports_ipv4:

            is_ipv4_exit = True

        if supports_ipv6:

            is_ipv6_exit = True

        # inferred_stack 兼容
        if inferred_stack in (
            "ipv4",
            "ipv4_only",
            "v4",
            "ipv4-only"
        ):

            is_ipv4_exit = True
            is_ipv6_exit = False

        elif inferred_stack in (
            "ipv6",
            "ipv6_only",
            "v6",
            "ipv6-only"
        ):

            is_ipv4_exit = False
            is_ipv6_exit = True

        elif inferred_stack in (
            "dual_stack",
            "dual",
            "ipv4_ipv6",
            "ipv4+ipv6"
        ):

            is_ipv4_exit = True
            is_ipv6_exit = True

    # ------------------------------------------------------------
    # 最终类型
    # ------------------------------------------------------------

    if is_ipv4_exit and is_ipv6_exit:

        exit_ip_type = "dual_stack"

    elif is_ipv4_exit:

        exit_ip_type = "ipv4"

    elif is_ipv6_exit:

        exit_ip_type = "ipv6"

    else:

        exit_ip_type = "unknown"

    # ------------------------------------------------------------
    # 返回判断结果
    # ------------------------------------------------------------

    return {
        "is_ipv4_exit": is_ipv4_exit,
        "is_ipv6_exit": is_ipv6_exit,
        "is_dual_stack_exit": (
            is_ipv4_exit and is_ipv6_exit
        ),
        "exit_ipv4": exit_ipv4,
        "exit_ipv6": exit_ipv6,
        "exit_ip_type": exit_ip_type
    }


# ============================================================
# 检查单个代理
# ============================================================

def check_proxy(proxy_info):
    """
    通过 Cloudflare Worker 检查代理。

    新增：
        is_ipv4_exit
        is_ipv6_exit
        is_dual_stack_exit
        exit_ipv4
        exit_ipv6
        exit_ip_type

    最终保存时只保留 IPv4 出口。
    """

    ip = proxy_info["ip"]
    port = proxy_info["port"]

    api_url = build_check_url(
        CHECK_API_URL,
        ip,
        port
    )

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 2
    ):

        try:

            start_time = time.perf_counter()

            response = session.get(
                api_url,
                timeout=REQUEST_TIMEOUT
            )

            elapsed = (
                time.perf_counter()
                - start_time
            ) * 1000

            response.raise_for_status()

            data = response.json()

            # --------------------------------------------------------
            # Worker 返回的响应时间
            # --------------------------------------------------------

            response_time = data.get(
                "responseTime",
                -1
            )

            try:

                if isinstance(
                    response_time,
                    str
                ):

                    response_time = float(
                        response_time
                    )

            except Exception:

                response_time = -1

            # --------------------------------------------------------
            # 判断出口 IP 类型
            # --------------------------------------------------------

            exit_info = detect_exit_ip_type(
                data
            )

            # --------------------------------------------------------
            # 整理结果
            # --------------------------------------------------------

            result = {
                "ip": ip,
                "port": port,

                "success": (
                    data.get(
                        "success",
                        False
                    ) is True
                ),

                "proxyIP": data.get(
                    "proxyIP",
                    "-1"
                ),

                "portRemote": data.get(
                    "portRemote",
                    -1
                ),

                "colo": data.get(
                    "colo",
                    ""
                ),

                "responseTime": response_time,

                "message": data.get(
                    "message",
                    ""
                ),

                "candidate": data.get(
                    "candidate",
                    f"{ip}:{port}"
                ),

                "inferred_stack": data.get(
                    "inferred_stack",
                    ""
                ),

                "supports_ipv4": data.get(
                    "supports_ipv4",
                    False
                ),

                "supports_ipv6": data.get(
                    "supports_ipv6",
                    False
                ),

                "dual_stack": data.get(
                    "dual_stack",
                    False
                ),

                # ----------------------------------------------------
                # 原始探针结果
                # ----------------------------------------------------

                "probe_results": data.get(
                    "probe_results",
                    {}
                ),

                # ----------------------------------------------------
                # 新增出口 IP 判断结果
                # ----------------------------------------------------

                "is_ipv4_exit": exit_info[
                    "is_ipv4_exit"
                ],

                "is_ipv6_exit": exit_info[
                    "is_ipv6_exit"
                ],

                "is_dual_stack_exit": exit_info[
                    "is_dual_stack_exit"
                ],

                "exit_ipv4": exit_info[
                    "exit_ipv4"
                ],

                "exit_ipv6": exit_info[
                    "exit_ipv6"
                ],

                "exit_ip_type": exit_info[
                    "exit_ip_type"
                ],

                # ----------------------------------------------------
                # 时间信息
                # ----------------------------------------------------

                "timestamp": data.get(
                    "timeStamp",
                    data.get(
                        "timestamp",
                        ""
                    )
                ),

                "http_elapsed": round(
                    elapsed,
                    2
                ),

                "attempt": attempt,

                "original_line": proxy_info[
                    "full_line"
                ],

                "error": ""
            }

            # --------------------------------------------------------
            # Worker 检测成功
            # --------------------------------------------------------

            if result["success"]:

                # ----------------------------------------------------
                # IPv4 出口
                # ----------------------------------------------------

                if result["is_ipv4_exit"]:

                    print(
                        f"✓ 有效 IPv4 出口 "
                        f"{ip}:{port} "
                        f"- 出口IP={result['exit_ipv4']} "
                        f"- {response_time}ms "
                        f"- colo={result['colo']} "
                        f"- stack={result['exit_ip_type']} "
                        f"- attempt={attempt}"
                    )

                # ----------------------------------------------------
                # IPv6 出口
                # ----------------------------------------------------

                elif result["is_ipv6_exit"]:

                    print(
                        f"✗ 过滤 IPv6 出口 "
                        f"{ip}:{port} "
                        f"- 出口IP={result['exit_ipv6']} "
                        f"- {response_time}ms "
                        f"- colo={result['colo']} "
                        f"- stack={result['exit_ip_type']}"
                    )

                # ----------------------------------------------------
                # 没有明确出口 IP
                # ----------------------------------------------------

                else:

                    print(
                        f"✗ 无法确定出口类型 "
                        f"{ip}:{port} "
                        f"- stack={result['exit_ip_type']} "
                        f"- attempt={attempt}"
                    )

                return result

            # --------------------------------------------------------
            # Worker 正常返回，但代理无效
            # --------------------------------------------------------

            print(
                f"✗ 无效 "
                f"{ip}:{port} "
                f"- {data.get('message', '')} "
                f"- attempt={attempt}"
            )

            return result

        # ============================================================
        # Timeout
        # ============================================================

        except requests.exceptions.ReadTimeout as e:

            last_error = (
                f"ReadTimeout: {e}"
            )

            print(
                f"⏱ 超时 "
                f"{ip}:{port} "
                f"- attempt={attempt}/"
                f"{MAX_RETRIES + 1}"
            )

        # ============================================================
        # Connection Error
        # ============================================================

        except requests.exceptions.ConnectionError as e:

            last_error = (
                f"ConnectionError: {e}"
            )

            print(
                f"🔌 连接失败 "
                f"{ip}:{port} "
                f"- attempt={attempt}/"
                f"{MAX_RETRIES + 1}"
            )

        # ============================================================
        # HTTP Error
        # ============================================================

        except requests.exceptions.HTTPError as e:

            last_error = (
                f"HTTPError: {e}"
            )

            print(
                f"🌐 HTTP错误 "
                f"{ip}:{port} "
                f"- {e}"
            )

            break

        # ============================================================
        # JSON Error
        # ============================================================

        except ValueError as e:

            last_error = (
                f"JSONError: {e}"
            )

            print(
                f"📄 JSON解析失败 "
                f"{ip}:{port}"
            )

            break

        # ============================================================
        # 其他错误
        # ============================================================

        except Exception as e:

            last_error = (
                f"{type(e).__name__}: {e}"
            )

            print(
                f"❌ 检查异常 "
                f"{ip}:{port} "
                f"- {e}"
            )

            break

        # ============================================================
        # Retry
        # ============================================================

        if attempt <= MAX_RETRIES:

            time.sleep(
                RETRY_DELAY
            )

    # ================================================================
    # 最终失败
    # ================================================================

    return {
        "ip": ip,
        "port": port,

        "success": False,

        "proxyIP": "-1",
        "portRemote": -1,
        "colo": "",
        "responseTime": -1,
        "message": "",

        "candidate": f"{ip}:{port}",

        "inferred_stack": "",

        "supports_ipv4": False,
        "supports_ipv6": False,
        "dual_stack": False,

        "probe_results": {},

        # 新增出口类型字段
        "is_ipv4_exit": False,
        "is_ipv6_exit": False,
        "is_dual_stack_exit": False,

        "exit_ipv4": "",
        "exit_ipv6": "",
        "exit_ip_type": "unknown",

        "timestamp": "",
        "http_elapsed": -1,

        "attempt": MAX_RETRIES + 1,

        "original_line": proxy_info[
            "full_line"
        ],

        "error": last_error or "unknown error"
    }


# ============================================================
# 批量检查
# ============================================================

def check_all_proxies(proxies):
    """
    并发检查所有代理
    """

    results = []

    total = len(proxies)

    print(
        f"\n开始检查 {total} 个代理"
    )

    print(
        f"并发数: {MAX_WORKERS}"
    )

    print(
        f"Worker timeout: "
        f"{WORKER_TIMEOUT_MS}ms"
    )

    print(
        f"Python timeout: "
        f"{REQUEST_TIMEOUT}s"
    )

    print(
        f"最大重试: "
        f"{MAX_RETRIES}"
    )

    print()

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                check_proxy,
                proxy
            ): proxy
            for proxy in proxies
        }

        for future in as_completed(
            future_map
        ):

            proxy = future_map[future]

            try:

                result = future.result()

                results.append(
                    result
                )

            except Exception as e:

                print(
                    f"任务执行失败: "
                    f"{proxy['ip']}:{proxy['port']} "
                    f"- {e}"
                )

            completed += 1

            if (
                completed % 10 == 0
                or completed == total
            ):

                print(
                    f"进度: "
                    f"{completed}/{total}"
                )

    return results


# ============================================================
# 保存有效 IPv4 出口 IP
# ============================================================

def save_valid_ips(
    results,
    filename=OUTPUT_FILENAME
):
    """
    保存条件：

    1. success=True
    2. is_ipv4_exit=True
    3. responseTime <= MAX_RESPONSE_TIME

    最终只写入候选 IP，不写端口。

    IPv6-only 出口直接过滤。
    双栈出口保留，因为它具备 IPv4 出口能力。
    """

    filtered = []

    for result in results:

        # --------------------------------------------------------
        # Worker 检测成功
        # --------------------------------------------------------

        success = result.get(
            "success",
            False
        )

        if not success:
            continue

        # --------------------------------------------------------
        # 只保留 IPv4 出口
        # --------------------------------------------------------

        is_ipv4_exit = result.get(
            "is_ipv4_exit",
            False
        )

        if not is_ipv4_exit:
            continue

        # --------------------------------------------------------
        # 响应时间
        # --------------------------------------------------------

        response_time = result.get(
            "responseTime",
            -1
        )

        if not isinstance(
            response_time,
            (int, float)
        ):
            continue

        if not (
            0 <= response_time
            <= MAX_RESPONSE_TIME
        ):
            continue

        filtered.append(
            result
        )

    # ------------------------------------------------------------
    # 延迟排序
    # ------------------------------------------------------------

    filtered.sort(
        key=lambda x: x.get(
            "responseTime",
            999999
        )
    )

    # ------------------------------------------------------------
    # IP 去重
    # ------------------------------------------------------------

    seen_ips = set()

    final_results = []

    for result in filtered:

        # 优先使用 Worker 返回的 IPv4 出口 IP
        # 如果不存在，则使用输入候选 IP
        ip = result.get(
            "exit_ipv4"
        ) or result.get(
            "ip",
            ""
        )

        if not ip:
            continue

        if ip in seen_ips:
            continue

        seen_ips.add(
            ip
        )

        # 保存出口 IP
        result["final_ip"] = ip

        final_results.append(
            result
        )

    # ------------------------------------------------------------
    # 写文件
    # ------------------------------------------------------------

    try:

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            for result in final_results:

                f.write(
                    f"{result['final_ip']}\n"
                )

        print(
            f"\n已保存 "
            f"{len(final_results)} 个有效 IPv4 出口 IP "
            f"到 {filename}"
        )

        return final_results

    except Exception as e:

        print(
            f"保存文件失败: {e}"
        )

        return []


# ============================================================
# 统计
# ============================================================

def print_statistics(
    proxies,
    results,
    filtered
):

    total = len(proxies)

    # ------------------------------------------------------------
    # Worker API 检测成功
    # ------------------------------------------------------------

    api_success = [
        r
        for r in results
        if r.get(
            "success"
        ) is True
    ]

    # ------------------------------------------------------------
    # IPv4 出口
    # ------------------------------------------------------------

    ipv4_exits = [
        r
        for r in api_success
        if r.get(
            "is_ipv4_exit"
        ) is True
    ]

    # ------------------------------------------------------------
    # IPv6 出口
    # ------------------------------------------------------------

    ipv6_exits = [
        r
        for r in api_success
        if (
            r.get(
                "is_ipv6_exit"
            ) is True
            and r.get(
                "is_ipv4_exit"
            ) is not True
        )
    ]

    # ------------------------------------------------------------
    # 双栈出口
    # ------------------------------------------------------------

    dual_stack_exits = [
        r
        for r in api_success
        if r.get(
            "is_dual_stack_exit"
        ) is True
    ]

    # ------------------------------------------------------------
    # 无法判断出口类型
    # ------------------------------------------------------------

    unknown_exits = [
        r
        for r in api_success
        if r.get(
            "exit_ip_type"
        ) == "unknown"
    ]

    # ------------------------------------------------------------
    # 超时
    # ------------------------------------------------------------

    timeouts = [
        r
        for r in results
        if "Timeout" in r.get(
            "error",
            ""
        )
    ]

    # ------------------------------------------------------------
    # 其他错误
    # ------------------------------------------------------------

    errors = [
        r
        for r in results
        if (
            r.get(
                "error"
            )
            and "Timeout"
            not in r.get(
                "error",
                ""
            )
        )
    ]

    # ------------------------------------------------------------
    # 打印统计
    # ------------------------------------------------------------

    print()
    print("=" * 60)
    print("统计信息")
    print("=" * 60)

    print(
        f"总代理数:          {total}"
    )

    print(
        f"完成检查:          {len(results)}"
    )

    print(
        f"API有效:           {len(api_success)}"
    )

    print(
        f"IPv4出口:          {len(ipv4_exits)}"
    )

    print(
        f"IPv6-only出口:     {len(ipv6_exits)}"
    )

    print(
        f"双栈出口:          {len(dual_stack_exits)}"
    )

    print(
        f"无法判断出口:       {len(unknown_exits)}"
    )

    print(
        f"超时:              {len(timeouts)}"
    )

    print(
        f"其他错误:          {len(errors)}"
    )

    print(
        f"IPv4且≤{MAX_RESPONSE_TIME}ms: "
        f"{len(filtered)}"
    )

    # ------------------------------------------------------------
    # 百分比
    # ------------------------------------------------------------

    if total:

        print(
            f"API有效率:         "
            f"{len(api_success) / total * 100:.2f}%"
        )

        print(
            f"IPv4出口占比:      "
            f"{len(ipv4_exits) / total * 100:.2f}%"
        )

        print(
            f"IPv4低延迟占比:   "
            f"{len(filtered) / total * 100:.2f}%"
        )

    print("=" * 60)


# ============================================================
# 打印最终结果
# ============================================================

def print_final_results(
    filtered
):

    if not filtered:

        print(
            "\n没有找到符合条件的 IPv4 出口代理"
        )

        return

    print()
    print(
        f"最终有效 IPv4 出口列表 "
        f"(≤ {MAX_RESPONSE_TIME}ms):"
    )

    print("-" * 80)

    for index, proxy in enumerate(
        filtered,
        1
    ):

        # 最终保存的 IPv4 出口地址
        ip = proxy.get(
            "final_ip",
            proxy.get(
                "exit_ipv4",
                proxy.get(
                    "ip",
                    ""
                )
            )
        )

        response_time = proxy.get(
            "responseTime",
            -1
        )

        colo = proxy.get(
            "colo",
            ""
        )

        stack = proxy.get(
            "exit_ip_type",
            "unknown"
        )

        print(
            f"{index:4d}. "
            f"{ip:<40} "
            f"{response_time:>6}ms "
            f"{colo:<6} "
            f"{stack}"
        )

    print("-" * 80)


# ============================================================
# 打印高延迟代理
# ============================================================

def print_slow_proxies(
    results
):

    slow = []

    for result in results:

        if result.get(
            "success"
        ) is not True:
            continue

        # 仅统计具有 IPv4 出口能力的代理
        if not result.get(
            "is_ipv4_exit",
            False
        ):
            continue

        response_time = result.get(
            "responseTime",
            -1
        )

        if (
            isinstance(
                response_time,
                (int, float)
            )
            and response_time
            > MAX_RESPONSE_TIME
        ):

            slow.append(
                result
            )

    slow.sort(
        key=lambda x: x.get(
            "responseTime",
            999999
        )
    )

    if not slow:
        return

    print()
    print(
        f"超过 {MAX_RESPONSE_TIME}ms 的 IPv4 有效代理:"
    )

    for result in slow:

        exit_ipv4 = result.get(
            "exit_ipv4",
            ""
        )

        print(
            f"  ✗ "
            f"{result['ip']}:{result['port']} "
            f"- 出口IPv4={exit_ipv4} "
            f"- {result['responseTime']}ms"
        )


# ============================================================
# 打印失败原因
# ============================================================

def print_failed_proxies(
    results
):

    failed = [
        r
        for r in results
        if r.get(
            "error"
        )
    ]

    if not failed:
        return

    print()
    print("请求失败列表:")
    print("-" * 60)

    for result in failed:

        print(
            f"{result['ip']}:{result['port']} "
            f"- {result.get('error', '')}"
        )

    print("-" * 60)


# ============================================================
# 打印 IPv6-only 代理
# ============================================================

def print_ipv6_only_proxies(
    results
):
    """
    打印检测成功，但只有 IPv6 出口的代理。

    这些代理不会被保存到 ip.txt。
    """

    ipv6_only = [
        r
        for r in results
        if (
            r.get(
                "success"
            ) is True
            and r.get(
                "is_ipv6_exit"
            ) is True
            and r.get(
                "is_ipv4_exit"
            ) is not True
        )
    ]

    if not ipv6_only:
        return

    print()
    print(
        f"IPv6-only 代理 (已过滤，不写入 {OUTPUT_FILENAME}):"
    )

    print("-" * 80)

    for result in ipv6_only:

        print(
            f"  IPv6 "
            f"{result['ip']}:{result['port']} "
            f"- 出口IPv6={result.get('exit_ipv6', '')} "
            f"- {result.get('responseTime', -1)}ms"
        )

    print("-" * 80)


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 60)
    print("Cloudflare Worker Proxy Checker")
    print("IPv4 Exit Only")
    print("=" * 60)

    print(
        f"目标国家:      {TARGET_COUNTRY}"
    )

    print(
        f"目标端口:      {TARGET_PORT}"
    )

    print(
        f"Worker timeout: "
        f"{WORKER_TIMEOUT_MS}ms"
    )

    print(
        f"Request timeout: "
        f"{REQUEST_TIMEOUT}s"
    )

    print(
        f"最大延迟:      "
        f"{MAX_RESPONSE_TIME}ms"
    )

    print(
        f"并发:          "
        f"{MAX_WORKERS}"
    )

    print()

    # ============================================================
    # 检查环境变量
    # ============================================================

    if not PROXY_FILE_URL:

        print(
            "错误: 未设置 "
            "PROXY_FILE_URL"
        )

        return

    if not CHECK_API_URL:

        print(
            "错误: 未设置 "
            "CHECK_API_URL"
        )

        return

    print(
        f"文件 URL: "
        f"{PROXY_FILE_URL}"
    )

    print(
        f"Worker URL: "
        f"{CHECK_API_URL}"
    )

    # ============================================================
    # Step 1
    # ============================================================

    print()
    print(
        "步骤 1/4: 下载代理文件"
    )

    if not download_file(
        PROXY_FILE_URL,
        LOCAL_FILENAME
    ):

        return

    # ============================================================
    # Step 2
    # ============================================================

    print()
    print(
        "步骤 2/4: 提取代理"
    )

    proxies = extract_proxies(
        LOCAL_FILENAME
    )

    if not proxies:

        print(
            "没有找到符合条件的代理"
        )

        return

    # ============================================================
    # Step 3
    # ============================================================

    print()
    print(
        "步骤 3/4: 检查代理"
    )

    start_time = time.perf_counter()

    results = check_all_proxies(
        proxies
    )

    total_time = (
        time.perf_counter()
        - start_time
    )

    print()
    print(
        f"全部检查完成，耗时 "
        f"{total_time:.2f} 秒"
    )

    # ============================================================
    # Step 4
    # ============================================================

    print()
    print(
        "步骤 4/4: 筛选 IPv4 出口结果"
    )

    filtered = save_valid_ips(
        results,
        OUTPUT_FILENAME
    )

    # ============================================================
    # Statistics
    # ============================================================

    print_statistics(
        proxies,
        results,
        filtered
    )

    # ============================================================
    # Final list
    # ============================================================

    print_final_results(
        filtered
    )

    # ============================================================
    # Slow proxies
    # ============================================================

    print_slow_proxies(
        results
    )

    # ============================================================
    # IPv6-only proxies
    # ============================================================

    print_ipv6_only_proxies(
        results
    )

    # ============================================================
    # Failed proxies
    # ============================================================

    print_failed_proxies(
        results
    )

    print()
    print("=" * 60)
    print("完成")
    print("=" * 60)


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":

    main()
