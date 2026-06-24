from datetime import datetime

from config import TIMELINE, MATCH, ADMIN, REFUND
from timesrc import TimeSrc
from bracket import Bracket
from match import Match
from player import Player
import shop as shop_mod
import settlement as settlement_mod
import persist
from reward import reward


def _parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


class Activity:
    """状态机 + 时间驱动迁移"""

    STATE_NOT_STARTED = "NOT_STARTED"
    STATE_LOGIN_OPEN = "LOGIN_OPEN"
    STATE_RUNNING = "RUNNING"
    STATE_SCORED = "SCORED"
    STATE_SETTLED = "SETTLED"

    def __init__(self, timesrc):
        self.timesrc = timesrc
        self.state = self.STATE_NOT_STARTED
        self.player_ids = [f"player_{i:02d}" for i in range(1, 33)]
        self.players = {}  # player_id -> Player（仅在线）
        self.logged_in = set()
        self.bracket = Bracket()
        self.current_round = 0
        self.current_matches = {}
        self._timeline_ts = {
            "login_open": _parse_ts(TIMELINE["login_open_ts"]),
            "start": _parse_ts(TIMELINE["start_ts"]),
            "settle": _parse_ts(TIMELINE["settle_ts"]),
        }
        shop_mod.init_shop()
        self._try_restore()

    def _player_online(self, player_id):
        """返回内存中的玩家对象。上线后才存在。"""
        return self.players.get(player_id)

    def _player_load(self, player_id):
        """从盘加载（上线用）"""
        if player_id in self.players:
            return self.players[player_id]
        p = Player(player_id)
        p.load()
        self.players[player_id] = p
        return p

    def _player_save(self, player_id):
        p = self.players.get(player_id)
        if p:
            p.save()

    def _player_unload(self, player_id):
        """下线销毁内存对象"""
        p = self.players.pop(player_id, None)
        if p:
            p.save()

    def _try_restore(self):
        snap = persist.load_snapshot()
        if not snap:
            self._save_full()
            return
        self.state = snap.get("state", self.STATE_NOT_STARTED)
        self.logged_in = set(snap.get("logged_in", []))
        self.current_round = snap.get("current_round", 0)
        if snap.get("bracket"):
            self.bracket = Bracket.from_dict(snap["bracket"])
        if snap.get("shop"):
            shop_mod.from_dict(snap["shop"])
        if snap.get("settlement"):
            settlement_mod.from_dict(snap["settlement"])
        self.current_matches = {}
        if snap.get("matches"):
            for k, v in snap["matches"].items():
                self.current_matches[int(k)] = Match.from_dict(v, self.timesrc)
        self._tick()

    def _save_full(self):
        persist.save_snapshot("state", self.state)
        persist.save_snapshot("logged_in", list(self.logged_in))
        persist.save_snapshot("current_round", self.current_round)
        persist.save_snapshot("shop", shop_mod.to_dict())
        persist.save_snapshot("settlement", settlement_mod.to_dict())
        persist.save_snapshot("matches", {str(k): v.to_dict() for k, v in self.current_matches.items()})

    def login(self, player_id):
        if player_id not in self.player_ids:
            return False, "invalid player_id"
        if self.state == self.STATE_NOT_STARTED:
            return False, "login not open yet"
        self._player_load(player_id)
        self.logged_in.add(player_id)
        self._save_full()

        for mi, m in self.current_matches.items():
            if player_id in (m.player_a, m.player_b) and not m.finished:
                state = m.get_state_for_player(player_id)
                return True, {"event": "resync", **state}

        return True, {"event": "ok", "state": self.state}

    def logout(self, player_id):
        self.logged_in.discard(player_id)
        self._player_unload(player_id)

    def query(self, player_id):
        p = self._player_online(player_id)
        return {
            "state": self.state,
            "score": p.score if p else 0,
            "current_round": self.current_round,
        }

    def play(self, player_id, move):
        if self.state != self.STATE_RUNNING:
            return False, "match not running"
        if move not in ("rock", "paper", "scissors"):
            return False, "invalid move"
        for mi, m in self.current_matches.items():
            if player_id in (m.player_a, m.player_b) and not m.finished:
                ok, msg = m.play(player_id, move)
                if ok:
                    self._save_full()
                    if m.finished:
                        self._on_match_finished(mi, m)
                return ok, msg
        return False, "no active match"

    def buy(self, player_id, item_id):
        if self.state != self.STATE_SCORED:
            return False, "shop not open"
        if settlement_mod.is_settled():
            return False, "already settled"
        p = self._player_online(player_id)
        if not p:
            return False, "not online"
        ok, msg = shop_mod.buy(player_id, item_id, self.timesrc, p)
        if ok:
            self._save_full()
        return ok, msg

    def _on_match_finished(self, match_index, match):
        winner_slot = match.slot_a if match.winner == match.player_a else match.slot_b
        self.bracket.record_winner(match.round_num, match_index, winner_slot)
        # 胜方玩家的 wins 计数
        p = self._player_online(match.winner)
        if p:
            p.add_win()
        del self.current_matches[match_index]
        self._save_full()

        if not self.current_matches:
            if match.round_num == 5:
                self._award_points()
                self.state = self.STATE_SCORED
            else:
                self._start_round(match.round_num + 1)
            self._save_full()

    def _award_points(self):
        for player_id in self.player_ids:
            wins = self.bracket.get_player_wins(player_id)
            pts = wins * MATCH["score_per_win"]
            if pts > 0:
                player = self._player_online(player_id)
                if player:
                    reward(player_id, "SCORE", pts, self.timesrc.now(), player)
                else:
                    offline_p = Player(player_id)
                    offline_p.load()
                    reward(player_id, "SCORE", pts, self.timesrc.now(), offline_p)

    def _start_round(self, round_num):
        self.current_round = round_num
        matchups = self.bracket.get_matchups(round_num)
        self.current_matches = {}
        for i, (slot_a, slot_b, player_a, player_b) in enumerate(matchups):
            m = Match(self.timesrc, round_num, i, slot_a, slot_b, player_a, player_b)
            self.current_matches[i] = m
        for m in self.current_matches.values():
            m.start()
        self._save_full()

    def _tick(self):
        now = self.timesrc.now()

        if self.state == self.STATE_NOT_STARTED and now >= self._timeline_ts["login_open"]:
            self.state = self.STATE_LOGIN_OPEN
            self._save_full()

        if self.state == self.STATE_LOGIN_OPEN and now >= self._timeline_ts["start"]:
            self.state = self.STATE_RUNNING
            if not self.bracket.slots:
                self.bracket.init_bracket(self.player_ids)
            self._start_round(1)
            self._save_full()

        if self.state == self.STATE_RUNNING:
            for mi, m in list(self.current_matches.items()):
                if m.check_timeout():
                    self._save_full()
                    if m.finished:
                        self._on_match_finished(mi, m)

        if self.state == self.STATE_SCORED and now >= self._timeline_ts["settle"]:
            self._settle_all()
            self.state = self.STATE_SETTLED
            self._save_full()

    def _settle_all(self):
        if settlement_mod.is_settled():
            return
        settlement_mod._settled = True
        for player_id in self.player_ids:
            player = self._player_online(player_id)
            if player and player.score > 0:
                coin = player.score * REFUND["point_to_coin_ratio"]
                player.deduct_score(player.score)
                reward(player_id, "梦幻币", coin, self.timesrc.now(), player)
            elif not player:
                offline_p = Player(player_id)
                offline_p.load()
                if offline_p.score > 0:
                    coin = offline_p.score * REFUND["point_to_coin_ratio"]
                    offline_p.deduct_score(offline_p.score)
                    reward(player_id, "梦幻币", coin, self.timesrc.now(), offline_p)

    def tick(self):
        self._tick()
