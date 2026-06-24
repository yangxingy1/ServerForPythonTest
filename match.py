from config import MATCH


class Match:
    """单场 3 局两胜"""

    def __init__(self, timesrc, round_num, match_index, slot_a, slot_b, player_a, player_b):
        self.timesrc = timesrc
        self.round_num = round_num
        self.match_index = match_index
        self.slot_a = slot_a
        self.slot_b = slot_b
        self.player_a = player_a
        self.player_b = player_b
        self.wins = {player_a: 0, player_b: 0}
        self.current_game = 0           # 0 = 未开始, 1/2/3
        self.current_mover = None       # 轮到谁出
        self.move_deadline = 0.0        # 出手截止时间戳
        self.game_history = []          # [{"game": 1, "move_a": "rock", "move_b": "scissors", "winner": "player_01"}, ...]
        self.finished = False
        self.winner = None

    def start(self):
        if self.current_game > 0:
            return
        self._start_game(1)

    def _start_game(self, game_num):
        self.current_game = game_num
        self.current_mover = "both"
        self.move_deadline = self.timesrc.now() + MATCH["move_timeout_sec"]

    def play(self, player_id, move):
        """玩家出手。返回 (accepted, msg)"""
        if self.finished:
            return False, "match already finished"
        if self.current_mover is None:
            return False, "not in move phase"
        if player_id not in (self.player_a, self.player_b):
            return False, "not your match"
        if self.current_mover != "both":
            return False, "waiting for opponent"

        # 记录出手
        a_moved = self._get_move(self.player_a)
        b_moved = self._get_move(self.player_b)

        if player_id == self.player_a and a_moved is not None:
            return False, "already moved"
        if player_id == self.player_b and b_moved is not None:
            return False, "already moved"

        self._set_move(player_id, move)

        # 检查双方是否都出了
        a_moved = self._get_move(self.player_a)
        b_moved = self._get_move(self.player_b)

        if a_moved is not None and b_moved is not None:
            self._resolve_game()
        return True, "ok"

    def check_timeout(self):
        """检查是否超时。若超时，自动判定。返回是否有变化。"""
        if self.finished:
            return False
        if self.current_mover != "both":
            return False
        now = self.timesrc.now()
        if now < self.move_deadline:
            return False

        a_moved = self._get_move(self.player_a)
        b_moved = self._get_move(self.player_b)

        # 双方都超时 → 平局重出
        if a_moved is None and b_moved is None:
            self._record_game(None, None, None)
            self._start_game(self.current_game)  # 同局重出，game 号不变，计时重置
            return True

        # 一方超时 → 另一方胜
        if a_moved is None:
            self._record_game(None, b_moved, self.player_b)
        elif b_moved is None:
            self._record_game(a_moved, None, self.player_a)
        else:
            # 双方都出了（不太可能走到这里，但安全处理）
            self._resolve_game()
            return True

        self._check_match_end()
        return True

    def _resolve_game(self):
        a_move = self._get_move(self.player_a)
        b_move = self._get_move(self.player_b)
        winner = self._judge(a_move, b_move)
        if winner is None:
            # 平局，重出
            self._record_game(a_move, b_move, None)
            self._start_game(self.current_game)
        else:
            winner_id = self.player_a if winner == "a" else self.player_b
            self._record_game(a_move, b_move, winner_id)
            self._check_match_end()

    def _judge(self, a, b):
        """返回 'a' / 'b' / None(平)"""
        if a == b:
            return None
        wins = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
        if wins[a] == b:
            return "a"
        return "b"

    def _record_game(self, move_a, move_b, winner):
        self.game_history.append({
            "game": self.current_game,
            "move_a": move_a,
            "move_b": move_b,
            "winner": winner,
        })
        self._clear_moves()
        if winner is not None:
            self.wins[winner] = self.wins.get(winner, 0) + 1

    def _check_match_end(self):
        if self.wins[self.player_a] >= 2:
            self.finished = True
            self.winner = self.player_a
            self.current_mover = None
        elif self.wins[self.player_b] >= 2:
            self.finished = True
            self.winner = self.player_b
            self.current_mover = None
        else:
            self._start_game(self.current_game + 1)

    def get_time_left(self, player_id):
        if self.finished or self.current_mover != "both":
            return None
        remaining = self.move_deadline - self.timesrc.now()
        return max(0, remaining)

    def get_state_for_player(self, player_id):
        """重连同步用"""
        opponent = self.player_b if player_id == self.player_a else self.player_a
        my_turn = (self.current_mover == "both")
        return {
            "round": self.round_num,
            "opponent": opponent,
            "my_wins": self.wins.get(player_id, 0),
            "opponent_wins": self.wins.get(opponent, 0),
            "game_history": self.game_history,
            "my_turn": my_turn,
            "time_left": self.get_time_left(player_id) if my_turn else None,
        }

    def _set_move(self, player_id, move):
        # 用未持久化的 dict 暂存
        if not hasattr(self, "_pending_moves"):
            self._pending_moves = {}
        self._pending_moves[player_id] = move

    def _get_move(self, player_id):
        if not hasattr(self, "_pending_moves"):
            return None
        return self._pending_moves.get(player_id)

    def _clear_moves(self):
        self._pending_moves = {}

    def to_dict(self):
        return {
            "round_num": self.round_num,
            "match_index": self.match_index,
            "slot_a": self.slot_a,
            "slot_b": self.slot_b,
            "player_a": self.player_a,
            "player_b": self.player_b,
            "wins": self.wins,
            "current_game": self.current_game,
            "current_mover": self.current_mover,
            "move_deadline": self.move_deadline,
            "game_history": self.game_history,
            "finished": self.finished,
            "winner": self.winner,
        }

    @classmethod
    def from_dict(cls, d, timesrc):
        m = cls(
            timesrc,
            d["round_num"],
            d["match_index"],
            d["slot_a"],
            d["slot_b"],
            d["player_a"],
            d["player_b"],
        )
        m.wins = d["wins"]
        m.current_game = d["current_game"]
        m.current_mover = d["current_mover"]
        m.move_deadline = d["move_deadline"]
        m.game_history = d["game_history"]
        m.finished = d["finished"]
        m.winner = d["winner"]
        return m
