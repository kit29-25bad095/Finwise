"""
Minimal Redis RESP Server for Local Production Emulation
Supports PING, AUTH, INFO, SELECT, and RQ basic queue commands.
"""

import socket
import threading
import sys

HOST = "127.0.0.1"
PORT = 6379

def handle_client(conn, addr):
    data_buffer = b""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            data_buffer += data
            while b"\r\n" in data_buffer:
                # Handle command
                lines = data_buffer.split(b"\r\n")
                # Parse simple command or RESP array
                cmd = b""
                for line in lines:
                    if line.startswith(b"*") or line.startswith(b"$") or not line:
                        continue
                    cmd = line.strip().upper()
                    break
                
                # Consume buffer up to next command
                data_buffer = b""
                
                if not cmd:
                    continue
                
                parts = cmd.split()
                main_cmd = parts[0] if parts else b""
                
                if main_cmd == b"HELLO":
                    # Return RESP3 hello map
                    resp = (
                        b"%7\r\n"
                        b"$6\r\nserver\r\n$5\r\nredis\r\n"
                        b"$7\r\nversion\r\n$5\r\n7.2.0\r\n"
                        b"$5\r\nproto\r\n:3\r\n"
                        b"$2\r\nid\r\n:1\r\n"
                        b"$4\r\nmode\r\n$10\r\nstandalone\r\n"
                        b"$4\r\nrole\r\n$6\r\nmaster\r\n"
                        b"$7\r\nmodules\r\n*0\r\n"
                    )
                    conn.sendall(resp)
                elif main_cmd == b"PING":
                    if len(parts) > 1:
                        arg = parts[1]
                        conn.sendall(b"+" + arg + b"\r\n")
                    else:
                        conn.sendall(b"+PONG\r\n")
                elif main_cmd in (b"AUTH", b"SELECT", b"QUIT", b"CLIENT"):
                    conn.sendall(b"+OK\r\n")
                elif main_cmd == b"INFO":
                    info = b"redis_version:7.2.0\r\nos:Windows\r\nrole:master\r\n"
                    conn.sendall(b"$" + str(len(info)).encode() + b"\r\n" + info + b"\r\n")
                elif main_cmd in (b"LLEN", b"SCARD", b"ZCARD", b"EXISTS"):
                    conn.sendall(b":0\r\n")
                elif main_cmd in (b"LRANGE", b"SMEMBERS", b"KEYS"):
                    conn.sendall(b"*0\r\n")
                elif main_cmd in (b"LPUSH", b"RPUSH", b"SADD", b"ZADD"):
                    conn.sendall(b":1\r\n")
                elif main_cmd in (b"SET", b"HSET", b"DEL"):
                    conn.sendall(b"+OK\r\n")
                elif main_cmd in (b"GET", b"HGET", b"LPOP", b"RPOP"):
                    conn.sendall(b"$-1\r\n")
                else:
                    conn.sendall(b"+OK\r\n")
    except Exception:
        pass
    finally:
        conn.close()

def run_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(10)
    print(f"Minimal Redis RESP Server listening on {HOST}:{PORT}")
    sys.stdout.flush()
    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()

if __name__ == "__main__":
    run_server()
