import random
from datetime import datetime
from config import PERSIST
import persist


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def generate_bracket(player_ids, seed=None):
    """随机打乱 32 个 player_id，填入 32 个槽位。返回槽位列表 (1-indexed)"""
    rng = random.Random(seed)
    shuffled = list(player_ids)
    rng.shuffle(shuffled)
    slots = {i + 1: shuffled[i] for i in range(32)}
    return slots


class Bracket:
    """固定槽位规则晋级"""

    def __init__(self):
        self.slots = {}          # slot_id -> player_id
        self.round_winners = {}  # round -> {match_index: winner_slot}
        self.total_rounds = 5    # 32 -> 16 -> 8 -> 4 -> 2 -> 1

    def init_bracket(self, player_ids, seed=None):
        self.slots = generate_bracket(player_ids, seed)
        self.round_winners = {}
        self._save()

    def get_matchups(self, round_num):
        """返回本轮所有对阵: [(slot_a, slot_b, player_a, player_b), ...]"""
        if round_num == 1:
            matchups = []
            for i in range(1, 33, 2):
                matchups.append((i, i + 1, self.slots[i], self.slots[i + 1]))
            return matchups
        prev_winners = self.round_winners.get(round_num - 1, {})
        matchups = []
        keys = sorted(prev_winners.keys())
        for i in range(0, len(keys), 2):
            slot_a = prev_winners[keys[i]]
            slot_b = prev_winners[keys[i + 1]]
            matchups.append((slot_a, slot_b, self.slots[slot_a], self.slots[slot_b]))
        return matchups

    def record_winner(self, round_num, match_index, winner_slot):
        if round_num not in self.round_winners:
            self.round_winners[round_num] = {}
        self.round_winners[round_num][match_index] = winner_slot
        self._save()

    def get_champion_slot(self):
        if self.total_rounds in self.round_winners:
            winners = self.round_winners[self.total_rounds]
            if 0 in winners:
                return winners[0]
        return None

    def get_champion(self):
        slot = self.get_champion_slot()
        if slot:
            return self.slots[slot]
        return None

    def get_player_wins(self, player_id):
        """统计该玩家累计胜场数"""
        wins = 0
        for match_index, winner_slot in self.round_winners.get(1, {}).items():
            if self.slots[winner_slot] == player_id:
                wins += 1
        for round_num in range(2, self.total_rounds + 1):
            for match_index, winner_slot in self.round_winners.get(round_num, {}).items():
                if self.slots[winner_slot] == player_id:
                    wins += 1
        return wins

    def _save(self):
        persist.save_snapshot("bracket", self.to_dict())

    def to_dict(self):
        return {
            "slots": self.slots,
            "round_winners": {str(k): v for k, v in self.round_winners.items()},
        }

    @classmethod
    def from_dict(cls, d):
        b = cls()
        b.slots = {int(k): v for k, v in d["slots"].items()}
        b.round_winners = {int(k): {int(k2): v2 for k2, v2 in v.items()} for k, v in d["round_winners"].items()}
        return b
