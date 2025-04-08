import re
with open('ip.txt', 'r', encoding='utf-8', errors='ignore') as f:
    data = f.read()
ips = re.findall(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', data)
def valid(ip):
    return all(0 <= int(part) <= 255 for part in ip.split('.'))
cleaned = sorted(set(filter(valid, ips)))
with open('ip.txt', 'w') as f:
    f.write('\\n'.join(cleaned))
