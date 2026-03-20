import socket

def scan_ports(ip, ports):
    print(f"Scanning {ip}...")
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((ip, port))
        if result == 0:
            print(f"Port {port} is OPEN")
        sock.close()

if __name__ == "__main__":
    target_ip = "192.168.68.114"
    common_ports = [80, 554, 5000, 5554, 8000, 8080, 8554]
    scan_ports(target_ip, common_ports)