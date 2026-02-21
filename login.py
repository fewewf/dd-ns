import requests
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

def download_file(url, filename):
    """下载文件"""
    try:
        response = requests.get(url)
        response.raise_for_status()
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"文件下载成功: {filename}")
        return True
    except Exception as e:
        print(f"文件下载失败: {e}")
        return False

def extract_us_proxies(filename):
    """提取US且端口8443的IP（格式: IP:PORT#COUNTRY）"""
    us_proxies = []

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    # 按 # 分割
                    ip_port, country = line.split('#')
                    country = country.strip()

                    # 按 : 分割
                    ip, port = ip_port.split(':')
                    ip = ip.strip()
                    port = port.strip()

                    # 过滤 US + 8443
                    if country == 'US' and port == '8443':
                        proxy_info = {
                            'ip': ip,
                            'port': port,
                            'full_line': line,
                            'line_num': line_num
                        }
                        us_proxies.append(proxy_info)

                except ValueError:
                    # 行格式错误跳过
                    continue

        print(f"找到 {len(us_proxies)} 个US且端口8443的代理")
        return us_proxies

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
            print(f"✓ 有效代理: {ip}:{port} - {result['message']}")
        else:
            print(f"✗ 无效代理: {ip}:{port}")
            
        return result
        
    except Exception as e:
        print(f"✗ 检查失败: {ip}:{port} - {e}")
        return {
            'ip': ip,
            'port': port,
            'success': False,
            'error': str(e)
        }

def save_valid_ips(valid_proxies, filename='ip.txt'):
    """保存有效的IP到文件（只保存IP，不包含端口）"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            for proxy in valid_proxies:
                f.write(f"{proxy['ip']}\n")  # 只写入IP，不包含端口
        
        print(f"\n已保存 {len(valid_proxies)} 个有效IP到 {filename}")
        
    except Exception as e:
        print(f"保存文件失败: {e}")

def main():
    # 从环境变量获取URL，如果不存在则使用默认值
    file_url = os.getenv("PROXY_FILE_URL")
    api_base_url = os.getenv("CHECK_API_URL")
    
    print(f"使用文件URL: {file_url}")
    print(f"使用API URL: {api_base_url}")
    
    local_filename = "us.txt"
    
    # 1. 下载文件
    print("步骤1: 下载文件...")
    if not download_file(file_url, local_filename):
        return
    
    # 2. 提取US且端口443的代理
    print("\n步骤2: 提取US且端口443的代理...")
    us_proxies = extract_us_proxies(local_filename)
    
    if not us_proxies:
        print("没有找到符合条件的代理")
        return
    
    # 3. 检查代理有效性
    print(f"\n步骤3: 检查代理有效性 (共 {len(us_proxies)} 个)...")
    valid_proxies = []
    
    # 使用线程池并发检查，提高效率
    max_workers = 10  # 控制并发数量，避免请求过快
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_proxy = {
            executor.submit(check_proxy, proxy, api_base_url): proxy 
            for proxy in us_proxies
        }
        
        # 处理完成的任务
        for future in as_completed(future_to_proxy):
            result = future.result()
            if result.get('success'):
                valid_proxies.append(result)
                
                # 如果已经找到15个有效代理，就停止
                if len(valid_proxies) >= 25:
                    print(f"\n已找到 {len(valid_proxies)} 个有效代理，停止检查")
                    # 取消剩余任务
                    for f in future_to_proxy:
                        f.cancel()
                    break
    
    # 4. 保存结果
    print(f"\n步骤4: 保存结果...")
    if valid_proxies:
        save_valid_ips(valid_proxies)
        
        # 打印统计信息
        print(f"\n=== 统计信息 ===")
        print(f"总检查代理数: {len(us_proxies)}")
        print(f"有效代理数: {len(valid_proxies)}")
        print(f"成功率: {len(valid_proxies)/len(us_proxies)*100:.2f}%")
        
        # 打印有效代理列表
        print(f"\n有效代理列表:")
        for i, proxy in enumerate(valid_proxies, 1):
            print(f"{i:2d}. {proxy['ip']} - {proxy['colo']} - {proxy['responseTime']}ms")
    else:
        print("没有找到有效的代理IP")

if __name__ == "__main__":
    main()
