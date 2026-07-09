import json
import os
import threading
from config import PERSIST


# 玩家级文件锁:每个 player_id 一把锁,串行化同名玩家文件的并发读写,
# 避免并发 login(读)/logout(写)读到写入中途的截断内容(BUG-9)。
_player_locks_guard = threading.Lock()
_player_locks = {}


def _player_lock(player_id):
    """返回(惰性创建)某玩家的专用文件锁。"""
    with _player_locks_guard:
        lock = _player_locks.get(player_id)
        if lock is None:
            lock = threading.Lock()
            _player_locks[player_id] = lock
        return lock


def _player_path(player_id):
    return os.path.join(PERSIST["player_data_dir"], f"{player_id}.json")


class Player:
    def __init__(self, player_id):
        self.player_id = player_id
        self.score = 0        # 积分
        self.coins = 0        # 梦幻币
        self.buys = {}        # item_id -> count
        self.rewards = []     # [{type, amount, ts}, ...]
        self.wins = 0

    # 从本地文件加载
    def load(self):
        path = _player_path(self.player_id)
        lock = _player_lock(self.player_id)
        with lock:
            if not os.path.exists(path):
                # 盘上没有 -> 按初始值落盘
                self._write_atomic()
                return
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.score = d.get("score", 0)
            self.coins = d.get("coins", 0)
            self.buys = d.get("buys", {})
            self.rewards = d.get("rewards", [])
            self.wins = d.get("wins", 0)

    # 原子写入:先写临时文件再 os.replace 重命名,避免并发读到半写内容(BUG-9)
    def _write_atomic(self):
        path = _player_path(self.player_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)

    # 写入本地文件(加锁 + 原子写)
    def save(self):
        lock = _player_lock(self.player_id)
        with lock:
            self._write_atomic()

    def add_win(self):
        self.wins += 1
        self.save()

    def record_buy(self, item_id, count):
        self.buys[item_id] = self.buys.get(item_id, 0) + count
        self.save()

    def get_buy_count(self, item_id):
        return self.buys.get(item_id, 0)

    def deduct_score(self, amount):
        if self.score < amount:
            return False
        self.score -= amount
        self.save()
        return True

    def to_dict(self):
        return {
            "player_id": self.player_id,
            "score": self.score,
            "coins": self.coins,
            "buys": self.buys,
            "rewards": self.rewards,
            "wins": self.wins,
        }
