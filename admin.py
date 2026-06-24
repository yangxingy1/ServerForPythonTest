import socket
import json
import sys
from config import ADMIN


def main():
    if len(sys.argv) < 2:
        print("Usage: python admin.py settime \"2026-07-01 18:00:00\"")
        print("       python admin.py advancetime 60")
        return

    cmd = sys.argv[1]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 9999))

    if cmd == "settime":
        ts = sys.argv[2] if len(sys.argv) > 2 else ""
        req = json.dumps({"cmd": "settime", "ts": ts, "token": ADMIN["token"]}) + "\n"
    elif cmd == "advancetime":
        seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        req = json.dumps({"cmd": "advancetime", "seconds": seconds, "token": ADMIN["token"]}) + "\n"
    else:
        print(f"Unknown command: {cmd}")
        return

    sock.sendall(req.encode("utf-8"))
    data = sock.recv(4096)
    resp = json.loads(data.decode("utf-8").strip())
    print(resp)
    sock.close()


if __name__ == "__main__":
    main()
