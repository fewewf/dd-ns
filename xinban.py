import dns.resolver
import requests
import json

def get_all_dns_records(domain):
    records = {
        'A': [],
        'AAAA': [],
        'CNAME': [],
        'MX': [],
        'NS': [],
        'TXT': []
    }
    
    for record_type in records.keys():
        try:
            answers = dns.resolver.resolve(domain, record_type)
            records[record_type] = [str(r) for r in answers]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except dns.resolver.NoNameservers:
            print(f"{domain}: DNS服务器无响应")
            return None
        except Exception as e:
            print(f"{domain}: 查询 {record_type} 记录时出错: {e}")
    
    return records

def check_proxy_ip(ip):
    """调用检测 API，返回 True 表示IP有效，False表示无效"""
    url = f"https://check.proxyip.cmliussss.net/check?proxyip={ip}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("success") is True:
            print(f"[✅ 正常] {ip} - {data.get('message')} - 节点: {data.get('colo')}")
            return True
        else:
            print(f"[❌ 异常] {ip} - {data.get('message')}")
            return False
    except Exception as e:
        print(f"[⚠️ 检测失败] {ip} - 错误: {e}")
        return False

# 支持多个域名
domains = [
    "ProxyIP.US.CMLiussss.net",
    "sjc.o00o.ooo"
]

# 去重
unique_ips = set()
valid_ips = []

with open("ip.txt", "w") as f:
    for domain in domains:
        print(f"\n正在查询域名: {domain}")
        records = get_all_dns_records(domain)
        
        if records:
            for record_type, values in records.items():
                if values:
                    for value in values:
                        # 只对 A 和 AAAA 记录做 IP 检测与去重
                        if record_type in ["A", "AAAA"]:
                            if value not in unique_ips:
                                unique_ips.add(value)
                                if check_proxy_ip(value):
                                    valid_ips.append(value)
                                    f.write(f"{value}\n")
            print(f"{domain} 的DNS记录已处理完成")
        else:
            print(f"{domain} 没有获取到DNS记录")

print("\n✅ 检测完成，有效 IP 已保存到 ip.txt")
