import socket
import json
import sys
import threading


def read_resp(sock):
    buf = b""
    while True:
        data = sock.recv(4096)
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            return json.loads(line.decode("utf-8"))
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <player_id>")
        return
    player_id = sys.argv[1]

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 9999))

    # 登录
    req = json.dumps({"cmd": "login", "player_id": player_id}) + "\n"
    sock.sendall(req.encode("utf-8"))
    resp = read_resp(sock)
    print(f"[CLIENT] login response: {resp}")

    def listen_loop():
        while True:
            try:
                r = read_resp(sock)
                if r is None:
                    break
                print(f"[CLIENT] event: {r}")
            except Exception:
                break

    listener = threading.Thread(target=listen_loop, daemon=True)
    listener.start()

    print("[CLIENT] Commands: play <rock|paper|scissors>, query, buy <item>, quit")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if line == "quit":
                break
            if line == "query":
                req = json.dumps({"cmd": "query", "player_id": player_id}) + "\n"
                sock.sendall(req.encode("utf-8"))
                r = read_resp(sock)
                print(f"  -> {r}")
            elif line.startswith("play "):
                move = line.split()[1]
                req = json.dumps({"cmd": "play", "player_id": player_id, "move": move}) + "\n"
                sock.sendall(req.encode("utf-8"))
                r = read_resp(sock)
                print(f"  -> {r}")
            elif line.startswith("buy "):
                item = line.split()[1]
                req = json.dumps({"cmd": "buy", "player_id": player_id, "item": item}) + "\n"
                sock.sendall(req.encode("utf-8"))
                r = read_resp(sock)
                print(f"  -> {r}")
            else:
                print("  unknown command")
        except KeyboardInterrupt:
            break

    sock.close()


if __name__ == "__main__":
    main()
