import socket
import json
import threading
import sys
from datetime import datetime

from config import CLOCK, ADMIN
from timesrc import TimeSrc
from activity import Activity


def _parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


class Server:
    def __init__(self, host="0.0.0.0", port=9999, boot_ts_str=None):
        self.timesrc = TimeSrc()
        boot_ts_str = boot_ts_str or CLOCK["boot_ts"]
        self.timesrc.set_time(_parse_ts(boot_ts_str))
        self.activity = Activity(self.timesrc)
        self.host = host
        self.port = port
        self.sessions = {}  # player_id -> socket

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(64)
        print(f"[SERVER] listening on {self.host}:{self.port}")
        print(f"[SERVER] boot time: {datetime.fromtimestamp(self.timesrc.now())}")

        while True:
            conn, addr = self.sock.accept()
            threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()

    def _handle_client(self, conn, addr):
        buf = b""
        player_id = None
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        req = json.loads(line.decode("utf-8"))
                    except Exception:
                        self._send(conn, {"event": "error", "msg": "invalid json"})
                        continue
                    resp = self._dispatch(req, conn)
                    if resp:
                        self._send(conn, resp)
                    # 记录 login 的 player_id 用于退出时 logout
                    if req.get("cmd") == "login":
                        player_id = req.get("player_id", "")
        except Exception as e:
            print(f"[SERVER] client error: {e}")
        finally:
            if player_id:
                self.activity.logout(player_id)
                self.sessions.pop(player_id, None)
            conn.close()

    def _dispatch(self, req, conn):
        cmd = req.get("cmd")

        # 管理指令需 token 鉴权
        if cmd in ("settime", "advancetime"):
            token = req.get("token", "")
            if token != ADMIN["token"]:
                return {"event": "error", "msg": "unauthorized"}
            if cmd == "settime":
                ts_str = req.get("ts", "")
                try:
                    target_ts = _parse_ts(ts_str)
                except Exception:
                    return {"event": "error", "msg": "invalid ts format"}
                self.timesrc.set_time(target_ts)
                print(f"[SERVER] time set to {ts_str}")
                self.activity.tick()
                return {"event": "ok", "msg": f"time set to {ts_str}"}
            elif cmd == "advancetime":
                seconds = req.get("seconds", 0)
                self.timesrc.advance(seconds)
                print(f"[SERVER] time advanced by {seconds}s, now {datetime.fromtimestamp(self.timesrc.now())}")
                self.activity.tick()
                return {"event": "ok", "msg": f"time advanced by {seconds}s"}

        # 普通指令
        if cmd == "login":
            player_id = req.get("player_id", "")
            ok, payload = self.activity.login(player_id)
            if ok:
                self.sessions[player_id] = conn
            return payload
        elif cmd == "query":
            return self.activity.query(req.get("player_id", ""))
        elif cmd == "play":
            player_id = req.get("player_id", "")
            move = req.get("move", "")
            ok, msg = self.activity.play(player_id, move)
            if ok:
                return {"event": "ok", "msg": msg}
            else:
                return {"event": "error", "msg": msg}
        elif cmd == "buy":
            player_id = req.get("player_id", "")
            item = req.get("item", "")
            ok, msg = self.activity.buy(player_id, item)
            if ok:
                return {"event": "ok", "msg": msg}
            else:
                return {"event": "error", "msg": msg}
        else:
            return {"event": "error", "msg": "unknown cmd"}

    def _send(self, conn, data):
        try:
            payload = json.dumps(data, ensure_ascii=False) + "\n"
            conn.sendall(payload.encode("utf-8"))
        except Exception:
            pass


if __name__ == "__main__":
    boot_ts = sys.argv[1] if len(sys.argv) > 1 else None
    srv = Server(boot_ts_str=boot_ts)
    srv.start()
