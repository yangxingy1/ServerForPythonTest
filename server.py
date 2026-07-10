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
        self.activity.set_notifier(self._notify_player)
        self.host = host
        self.port = port
        self.sessions = {}  # player_id -> socket
        self._sessions_lock = threading.Lock()

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
                    resp = self._dispatch(req, conn, player_id)
                    if resp:
                        self._send(conn, resp)
                    if req.get("cmd") == "login":
                        player_id = req.get("player_id", "")
        except Exception as e:
            print(f"[SERVER] client error: {e}")
        finally:
            if player_id:
                self.activity.logout(player_id)
                self._unregister_session(player_id, conn)
            conn.close()

    def _register_session(self, player_id, conn):
        with self._sessions_lock:
            self.sessions[player_id] = conn

    def _unregister_session(self, player_id, conn):
        with self._sessions_lock:
            # 仅当仍是本连接占位时才移除,避免被后一次 login 的连接误删(重连竞态)。
            if self.sessions.get(player_id) is conn:
                self.sessions.pop(player_id, None)

    def _notify_player(self, player_id, event):
        with self._sessions_lock:
            conn = self.sessions.get(player_id)
        if conn is not None:
            self._send(conn, event)

    def _player_id_for(self, req, conn, fallback_pid):
        player_id = req.get("player_id")
        if player_id:
            return player_id
        # 指令未带 player_id:用本连接已 login 的玩家。
        if fallback_pid:
            return fallback_pid
        return ""

    def _dispatch(self, req, conn, fallback_pid=None):
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
                self._register_session(player_id, conn)
                return payload
            else:
                return {"event": "error", "msg": payload}
        elif cmd == "query":
            player_id = self._player_id_for(req, conn, fallback_pid)
            return self.activity.query(player_id)
        elif cmd == "play":
            player_id = self._player_id_for(req, conn, fallback_pid)
            move = req.get("move", "")
            ok, msg = self.activity.play(player_id, move)
            if ok:
                return {"event": "ok", "msg": msg}
            else:
                return {"event": "error", "msg": msg}
        elif cmd == "buy":
            player_id = self._player_id_for(req, conn, fallback_pid)
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
