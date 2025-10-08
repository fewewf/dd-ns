import csv
import requests
from io import StringIO

def download_and_extract_ips():
    url = "https://raw.githubusercontent.com/ymyuuu/IPDB/refs/heads/main/BestProxy/proxy.csv"
    response = requests.get(url)
    
    if response.status_code != 200:
        print(f"下载文件失败，HTTP状态码: {response.status_code}")
        return
    
    csv_content = StringIO(response.text)
    reader = csv.reader(csv_content, delimiter='\t')
    
    # 跳过表头（第一行）
    next(reader, None)
    
    ips = []
    for row in reader:
        if row:  # 确保不是空行
            ips.append(row[0])  # 取第一列
    
    with open('ip.txt', 'w') as f:
        for ip in ips:
            f.write(ip + '\n')
    
    print(f"成功提取并保存了{len(ips)}个IP地址到ip.txt")

if __name__ == "__main__":
    download_and_extract_ips()
