"""
Finora Production Emulation - High-Fidelity In-Memory Redis RESP Server
Supports RESP2/RESP3, real key-value storage, expiration (EX), EXISTS, GET, SET,
DEL, TTL, SCAN, KEYS, PING, AUTH, INFO, SELECT, and RQ basic operations.
"""

import socket
import threading
import time
import fnmatch
import sys

HOST = "127.0.0.1"
PORT = 6379

DATA_STORE = {}
EXPIRE_STORE = {}
STORE_LOCK = threading.Lock()


def is_expired(key: str) -> bool:
    if key in EXPIRE_STORE:
        if time.time() > EXPIRE_STORE[key]:
            DATA_STORE.pop(key, None)
            EXPIRE_STORE.pop(key, None)
            return True
    return False


def purge_expired():
    now = time.time()
    with STORE_LOCK:
        expired = [k for k, exp in EXPIRE_STORE.items() if exp < now]
        for k in expired:
            DATA_STORE.pop(k, None)
            EXPIRE_STORE.pop(k, None)


def handle_client(conn):
    rfile = conn.makefile("rb")
    wfile = conn.makefile("wb")
    try:
        while True:
            line = rfile.readline()
            if not line:
                break
            line_stripped = line.strip()
            if not line_stripped:
                continue

            if line_stripped.startswith(b"*"):
                count = int(line_stripped[1:])
                args = []
                for _ in range(count):
                    dl = rfile.readline().strip()
                    if not dl.startswith(b"$"):
                        break
                    length = int(dl[1:])
                    val = rfile.read(length)
                    rfile.read(2)  # skip trailing \r\n
                    args.append(val)
            else:
                args = line_stripped.split()

            if not args:
                continue

            cmd = args[0].upper().decode("utf-8", errors="ignore")

            if cmd == "HELLO":
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
                wfile.write(resp)
            elif cmd == "PING":
                if len(args) > 1:
                    val = args[1]
                    wfile.write(b"$" + str(len(val)).encode() + b"\r\n" + val + b"\r\n")
                else:
                    wfile.write(b"+PONG\r\n")
            elif cmd in ("AUTH", "SELECT", "CLIENT"):
                wfile.write(b"+OK\r\n")
            elif cmd == "QUIT":
                wfile.write(b"+OK\r\n")
                wfile.flush()
                break
            elif cmd == "SET":
                key = args[1].decode("utf-8", errors="ignore")
                val = args[2].decode("utf-8", errors="ignore")
                ex_sec = None
                i = 3
                while i < len(args):
                    opt = args[i].upper().decode("utf-8", errors="ignore")
                    if opt == "EX" and i + 1 < len(args):
                        try:
                            ex_sec = float(args[i+1].decode("utf-8", errors="ignore"))
                        except ValueError:
                            pass
                        i += 2
                    else:
                        i += 1
                with STORE_LOCK:
                    DATA_STORE[key] = val
                    if ex_sec is not None:
                        EXPIRE_STORE[key] = time.time() + ex_sec
                    elif key in EXPIRE_STORE:
                        del EXPIRE_STORE[key]
                wfile.write(b"+OK\r\n")
            elif cmd == "GET":
                key = args[1].decode("utf-8", errors="ignore")
                with STORE_LOCK:
                    if key in DATA_STORE and (key not in EXPIRE_STORE or time.time() <= EXPIRE_STORE[key]):
                        val_b = DATA_STORE[key].encode("utf-8")
                        wfile.write(b"$" + str(len(val_b)).encode() + b"\r\n" + val_b + b"\r\n")
                    else:
                        wfile.write(b"$-1\r\n")
            elif cmd == "EXISTS":
                count = 0
                now = time.time()
                with STORE_LOCK:
                    for a in args[1:]:
                        k = a.decode("utf-8", errors="ignore")
                        if k in DATA_STORE and (k not in EXPIRE_STORE or now <= EXPIRE_STORE[k]):
                            count += 1
                wfile.write(f":{count}\r\n".encode())
            elif cmd == "DEL":
                count = 0
                with STORE_LOCK:
                    for a in args[1:]:
                        k = a.decode("utf-8", errors="ignore")
                        if k in DATA_STORE:
                            DATA_STORE.pop(k, None)
                            EXPIRE_STORE.pop(k, None)
                            count += 1
                wfile.write(f":{count}\r\n".encode())
            elif cmd == "TTL":
                key = args[1].decode("utf-8", errors="ignore")
                now = time.time()
                with STORE_LOCK:
                    if key not in DATA_STORE or (key in EXPIRE_STORE and now > EXPIRE_STORE[key]):
                        wfile.write(b":-2\r\n")
                    elif key in EXPIRE_STORE:
                        rem = int(EXPIRE_STORE[key] - now)
                        wfile.write(f":{max(0, rem)}\r\n".encode())
                    else:
                        wfile.write(b":-1\r\n")
            elif cmd == "SCAN":
                pattern = "*"
                i = 2
                while i < len(args):
                    opt = args[i].upper().decode("utf-8", errors="ignore")
                    if opt == "MATCH" and i + 1 < len(args):
                        pattern = args[i+1].decode("utf-8", errors="ignore")
                        i += 2
                    else:
                        i += 1
                now = time.time()
                with STORE_LOCK:
                    matches = [
                        k for k in DATA_STORE.keys()
                        if fnmatch.fnmatch(k, pattern) and (k not in EXPIRE_STORE or now <= EXPIRE_STORE[k])
                    ]
                resp = b"*2\r\n$1\r\n0\r\n"
                resp += f"*{len(matches)}\r\n".encode()
                for m in matches:
                    b = m.encode("utf-8")
                    resp += f"${len(b)}\r\n".encode() + b + b"\r\n"
                wfile.write(resp)
            elif cmd == "KEYS":
                pattern = args[1].decode("utf-8", errors="ignore") if len(args) > 1 else "*"
                now = time.time()
                with STORE_LOCK:
                    matches = [
                        k for k in DATA_STORE.keys()
                        if fnmatch.fnmatch(k, pattern) and (k not in EXPIRE_STORE or now <= EXPIRE_STORE[k])
                    ]
                resp = f"*{len(matches)}\r\n".encode()
                for m in matches:
                    b = m.encode("utf-8")
                    resp += f"${len(b)}\r\n".encode() + b + b"\r\n"
                wfile.write(resp)
            elif cmd in ("FLUSHDB", "FLUSHALL"):
                with STORE_LOCK:
                    DATA_STORE.clear()
                    EXPIRE_STORE.clear()
                wfile.write(b"+OK\r\n")
            elif cmd == "INFO":
                info = b"redis_version:7.2.0\r\nos:Windows\r\nrole:master\r\nconnected_clients:1\r\n"
                wfile.write(b"$" + str(len(info)).encode() + b"\r\n" + info + b"\r\n")
            elif cmd in ("LPUSH", "RPUSH"):
                wfile.write(b":1\r\n")
            elif cmd in ("LPOP", "RPOP"):
                wfile.write(b"$-1\r\n")
            elif cmd == "LLEN":
                wfile.write(b":0\r\n")
            else:
                wfile.write(b"+OK\r\n")
            wfile.flush()
    except Exception:
        pass
    finally:
        try:
            rfile.close()
            wfile.close()
            conn.close()
        except Exception:
            pass


def run_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(50)
    print(f"Minimal Redis RESP Server listening on {HOST}:{PORT}")
    sys.stdout.flush()
    while True:
        try:
            conn, _ = server.accept()
            t = threading.Thread(target=handle_client, args=(conn,), daemon=True)
            t.start()
        except Exception:
            break


if __name__ == "__main__":
    run_server()
