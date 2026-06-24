import json
import os
from config import PERSIST


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

    def load(self):
        path = _player_path(self.player_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.score = d.get("score", 0)
            self.coins = d.get("coins", 0)
            self.buys = d.get("buys", {})
            self.rewards = d.get("rewards", [])
            self.wins = d.get("wins", 0)
        else:
            self.save()

    def save(self):
        path = _player_path(self.player_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

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
