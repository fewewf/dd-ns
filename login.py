import requests
import os
from concurrent.futures import ThreadPoolExecutor, as_completed


def download_file(url, filename):
    """下载文件"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(response.text)

        print(f"文件下载成功: {filename}")
        return True

    except Exception as e:
        print(f"文件下载失败: {e}")
        return False


def extract_us_proxies(filename):
    """提取指定国家且端口8443的IP（格式: IP:PORT#COUNTRY）"""
    proxies = []

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()

                if not line:
                    continue

                try:
                    # 按 # 分割
                    ip_port, country = line.split('#', 1)
                    country = country.strip()

                    # 按 : 分割
                    ip, port = ip_port.split(':', 1)
                    ip = ip.strip()
                    port = port.strip()

                    # 过滤 JP + 8443
                    # 如果实际需要 US，请将 JP 改成 US
                    if country == 'JP' and port == '8443':
                        proxy_info = {
                            'ip': ip,
                            'port': port,
                            'full_line': line,
                            'line_num': line_num
                        }

                        proxies.append(proxy_info)

                except ValueError:
                    # 行格式错误跳过
                    continue

        print(f"找到 {len(proxies)} 个JP且端口8443的代理")
        return proxies

    except Exception as e:
        print(f"读取文件失败: {e}")
        return []


def check_proxy(proxy_info, api_base_url):
    """检查代理IP是否有效"""

    ip = proxy_info['ip']
    port = proxy_info['port']
    proxy_url = f"{ip}:{port}"

    api_url = f"{api_base_url}/check?proxyip={proxy_url}&token=zfwkn"

    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()

        data = response.json()

        result = {
            'ip': ip,
            'port': port,
            'success': data.get('success', False),
            'proxyIP': data.get('proxyIP', '-1'),
            'portRemote': data.get('portRemote', -1),
            'colo': data.get('colo', ''),
            'responseTime': data.get('responseTime', -1),
            'message': data.get('message', ''),
            'timestamp': data.get('timestamp', ''),
            'original_line': proxy_info['full_line']
        }

        if result['success']:
            print(
                f"✓ 有效代理: {ip}:{port} - "
                f"{result['responseTime']}ms - "
                f"{result['message']}"
            )
        else:
            print(f"✗ 无效代理: {ip}:{port}")

        return result

    except Exception as e:
        print(f"✗ 检查失败: {ip}:{port} - {e}")

        return {
            'ip': ip,
            'port': port,
            'success': False,
            'responseTime': -1,
            'error': str(e)
        }


def save_valid_ips(valid_proxies, filename='ip.txt'):
    """
    保存有效IP：
    1. 过滤 responseTime <= 600ms
    2. 按 responseTime 从低到高排序
    3. 只保存IP，不保存端口
    """

    try:
        # 只保留有效且延迟 <= 600ms 的代理
        filtered_proxies = [
            proxy
            for proxy in valid_proxies
            if proxy.get('success') is True
            and isinstance(proxy.get('responseTime'), (int, float))
            and 0 <= proxy.get('responseTime') <= 600
        ]

        # 按延迟从低到高排序
        filtered_proxies.sort(
            key=lambda proxy: proxy['responseTime']
        )

        # 保存，只写IP
        with open(filename, 'w', encoding='utf-8') as f:
            for proxy in filtered_proxies:
                f.write(f"{proxy['ip']}\n")

        print(
            f"\n已保存 {len(filtered_proxies)} 个有效IP到 {filename}"
        )

        return filtered_proxies

    except Exception as e:
        print(f"保存文件失败: {e}")
        return []


def main():
    # 从环境变量获取URL
    file_url = os.getenv("PROXY_FILE_URL")
    api_base_url = os.getenv("CHECK_API_URL")

    print(f"使用文件URL: {file_url}")
    print(f"使用API URL: {api_base_url}")

    local_filename = "us.txt"

    # 1. 下载文件
    print("\n步骤1: 下载文件...")

    if not file_url:
        print("错误: 未设置 PROXY_FILE_URL")
        return

    if not api_base_url:
        print("错误: 未设置 CHECK_API_URL")
        return

    if not download_file(file_url, local_filename):
        return

    # 2. 提取JP且端口8443的代理
    print("\n步骤2: 提取JP且端口8443的代理...")

    us_proxies = extract_us_proxies(local_filename)

    if not us_proxies:
        print("没有找到符合条件的代理")
        return

    # 3. 检查代理有效性
    print(
        f"\n步骤3: 检查代理有效性 "
        f"(共 {len(us_proxies)} 个)..."
    )

    valid_proxies = []

    # 并发检查
    max_workers = 10

    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        future_to_proxy = {
            executor.submit(
                check_proxy,
                proxy,
                api_base_url
            ): proxy
            for proxy in us_proxies
        }

        # 等待所有任务完成
        for future in as_completed(future_to_proxy):

            try:
                result = future.result()

                if result.get('success'):
                    valid_proxies.append(result)

            except Exception as e:
                print(f"任务执行失败: {e}")

    # 4. 保存结果
    print("\n步骤4: 筛选并保存结果...")

    if valid_proxies:

        # 过滤 <= 600ms 并排序
        filtered_proxies = save_valid_ips(
            valid_proxies,
            filename='ip.txt'
        )

        # 统计
        print("\n=== 统计信息 ===")
        print(f"总检查代理数: {len(us_proxies)}")
        print(f"API有效代理数: {len(valid_proxies)}")
        print(f"600ms以内代理数: {len(filtered_proxies)}")

        if valid_proxies:
            print(
                f"API有效率: "
                f"{len(valid_proxies) / len(us_proxies) * 100:.2f}%"
            )

        if filtered_proxies:
            print(
                f"600ms以内占总数: "
                f"{len(filtered_proxies) / len(us_proxies) * 100:.2f}%"
            )

        # 打印最终保存列表
        print("\n最终保存列表（按延迟从低到高）:")

        for i, proxy in enumerate(filtered_proxies, 1):
            print(
                f"{i:2d}. "
                f"{proxy['ip']} - "
                f"{proxy['colo']} - "
                f"{proxy['responseTime']}ms"
            )

        # 显示被过滤掉的高延迟代理
        over_600 = [
            proxy
            for proxy in valid_proxies
            if isinstance(proxy.get('responseTime'), (int, float))
            and proxy.get('responseTime') > 600
        ]

        if over_600:
            print("\n已过滤掉超过600ms的代理:")

            for proxy in sorted(
                over_600,
                key=lambda x: x.get('responseTime', 999999)
            ):
                print(
                    f"  ✗ {proxy['ip']} - "
                    f"{proxy['responseTime']}ms"
                )

    else:
        print("没有找到有效的代理IP")


if __name__ == "__main__":
    main()
