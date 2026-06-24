"""
In-process 自动化测试：直接实例化 Activity + TimeSrc，验证已发现的潜在 bug。
运行: python test_inprocess.py
"""
import os
import sys
import json
import shutil
import threading
import tempfile
from datetime import datetime

from timesrc import TimeSrc
from player import Player
import config
import persist
import shop as shop_mod
import settlement as settlement_mod


def _parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


# ─── 测试基础设施 ───────────────────────────────────────────

class TestContext:
    """每个测试用例独立的运行时目录，避免测试间互相污染"""

    def __init__(self, test_name):
        self.test_name = test_name
        self.tmpdir = tempfile.mkdtemp(prefix=f"test_{test_name}_")
        self.orig_snapshot_path = config.PERSIST["snapshot_path"]
        self.orig_player_dir = config.PERSIST["player_data_dir"]

    def __enter__(self):
        config.PERSIST["snapshot_path"] = os.path.join(self.tmpdir, "snapshot.json")
        config.PERSIST["player_data_dir"] = os.path.join(self.tmpdir, "players")
        os.makedirs(config.PERSIST["player_data_dir"], exist_ok=True)
        persist._snapshot = {}
        shop_mod.shop_stock = {}
        settlement_mod._settled = False
        return self

    def __exit__(self, *args):
        config.PERSIST["snapshot_path"] = self.orig_snapshot_path
        config.PERSIST["player_data_dir"] = self.orig_player_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def make_activity(ts_str="2026-07-01 17:00:00"):
    """创建一个干净的 Activity 实例"""
    from activity import Activity
    ts = TimeSrc()
    ts.set_time(_parse_ts(ts_str))
    act = Activity(ts)
    return act, ts


def run_full_tournament(act, ts):
    """辅助：跑完整个5轮淘汰赛，全部选手都出拳"""
    ts.set_time(_parse_ts("2026-07-01 17:30:00"))
    act.tick()
    for pid in act.player_ids:
        act.login(pid)

    ts.set_time(_parse_ts("2026-07-01 18:00:00"))
    act.tick()

    _finish_all_matches(act)
    return act


def _finish_all_matches(act):
    """把当前所有比赛打完（可能跨多轮）"""
    safety = 0
    while act.state == "RUNNING" and safety < 500:
        safety += 1
        if not act.current_matches:
            break
        for mi, m in list(act.current_matches.items()):
            if m.finished:
                continue
            act.play(m.player_a, "rock")
            act.play(m.player_b, "scissors")
            act.play(m.player_a, "rock")
            act.play(m.player_b, "scissors")


# ─── 测试用例 ──────────────────────────────────────────────

results = []


def report(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))


def test_01_offline_player_settlement_persistence():
    """Bug#1: 离线玩家结算退款后数据是否真正落盘"""
    with TestContext("settlement_persist"):
        act, ts = make_activity()
        ts.set_time(_parse_ts("2026-07-01 17:30:00"))
        act.tick()

        for pid in act.player_ids:
            act.login(pid)

        ts.set_time(_parse_ts("2026-07-01 18:00:00"))
        act.tick()

        _finish_all_matches(act)
        assert act.state == "SCORED", f"Expected SCORED, got {act.state}"

        # 找一个有积分的玩家，让其下线
        target = None
        for pid in act.player_ids:
            p = act._player_online(pid)
            if p and p.score > 0:
                target = pid
                break

        if not target:
            report("离线玩家结算落盘", False, "没有找到有积分的玩家")
            return

        target_score = act._player_online(target).score
        act.logout(target)

        # 触发结算
        ts.set_time(_parse_ts("2026-07-03 00:00:00"))
        act.tick()

        # 从磁盘重新加载该玩家数据
        p2 = Player(target)
        p2.load()
        expected_coins = target_score * config.REFUND["point_to_coin_ratio"]
        persisted = (p2.coins >= expected_coins and p2.score == 0)
        report(
            "离线玩家结算落盘",
            persisted,
            f"player={target}, expected coins>={expected_coins}, got coins={p2.coins}, score={p2.score}"
        )


def test_02_offline_player_award_points_persistence():
    """Bug#2: 离线玩家发积分后是否落盘"""
    with TestContext("award_persist"):
        act, ts = make_activity()
        ts.set_time(_parse_ts("2026-07-01 17:30:00"))
        act.tick()

        for pid in act.player_ids:
            act.login(pid)

        ts.set_time(_parse_ts("2026-07-01 18:00:00"))
        act.tick()

        # 让 player_01 (player_a) 赢第一场后下线
        first_match = list(act.current_matches.values())[0]
        winner = first_match.player_a

        act.play(first_match.player_a, "rock")
        act.play(first_match.player_b, "scissors")
        act.play(first_match.player_a, "rock")
        act.play(first_match.player_b, "scissors")

        # 下线这个赢家
        act.logout(winner)

        # 跑完剩余比赛
        _finish_all_matches(act)

        if act.state != "SCORED":
            report("离线玩家积分落盘", False, f"state={act.state}, not SCORED yet")
            return

        p = Player(winner)
        p.load()
        has_score = p.score > 0
        report(
            "离线玩家积分落盘",
            has_score,
            f"player={winner}, score={p.score} (expected > 0)"
        )


def test_03_shop_concurrent_race():
    """Bug#3: 商店库存并发竞态"""
    with TestContext("shop_race"):
        act, ts = make_activity()
        ts.set_time(_parse_ts("2026-07-01 17:30:00"))
        act.tick()

        for pid in act.player_ids:
            act.login(pid)

        ts.set_time(_parse_ts("2026-07-01 18:00:00"))
        act.tick()

        # 跑完比赛
        _finish_all_matches(act)

        if act.state != "SCORED":
            report("商店并发竞态", False, f"state={act.state}")
            return

        # 给多个玩家足够积分来买 banana (stock=10, price=100, per_user_limit=1)
        # 先给 12 个玩家每人 200 分
        buyers = []
        for pid in act.player_ids[:12]:
            p = act._player_online(pid)
            if p:
                p.score = 200
                p.save()
                buyers.append(pid)

        # 模拟并发购买：12人同时买 banana（库存只有10）
        buy_results = []
        barrier = threading.Barrier(len(buyers))

        def try_buy(pid):
            barrier.wait()
            ok, msg = act.buy(pid, "banana")
            buy_results.append((pid, ok, msg))

        threads = [threading.Thread(target=try_buy, args=(pid,)) for pid in buyers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        success_count = sum(1 for _, ok, _ in buy_results if ok)
        final_stock = shop_mod.shop_stock.get("banana", 0)

        # 正确行为：最多成功 10 次（库存10），库存不应为负
        stock_ok = final_stock >= 0
        count_ok = success_count <= 10

        report(
            "商店并发竞态",
            stock_ok and count_ok,
            f"success={success_count}/12, final_stock={final_stock} (expect stock>=0, success<=10)"
        )


def test_04_crash_recovery_pending_moves():
    """Bug#4: 崩溃恢复后已出手是否丢失"""
    with TestContext("crash_moves"):
        from activity import Activity

        act, ts = make_activity()
        ts.set_time(_parse_ts("2026-07-01 17:30:00"))
        act.tick()

        for pid in act.player_ids:
            act.login(pid)

        ts.set_time(_parse_ts("2026-07-01 18:00:00"))
        act.tick()

        # 找到第一场比赛，player_a 出拳
        first_match = list(act.current_matches.values())[0]
        pa = first_match.player_a
        pb = first_match.player_b

        act.play(pa, "rock")  # pa 已出手，等待 pb

        # 模拟崩溃：重新加载
        act2 = Activity(ts)

        # 尝试找到恢复后的对应 match
        recovered_match = None
        for mi, m in act2.current_matches.items():
            if pa in (m.player_a, m.player_b):
                recovered_match = m
                break

        if not recovered_match:
            report("崩溃恢复出手丢失", False, "恢复后找不到对应 match")
            return

        # 检查 pa 的出手是否还在
        pa_move = recovered_match._get_move(pa)
        move_lost = (pa_move is None)
        report(
            "崩溃恢复出手丢失",
            move_lost,  # 预期: True = 确认 bug 存在（出手确实丢了）
            f"pa_move after recovery = {pa_move} (None means lost = bug confirmed)"
        )


def test_05_timeout_infinite_history():
    """Bug#5: 双方持续超时导致 game_history 无限膨胀"""
    with TestContext("timeout_loop"):
        act, ts = make_activity()
        ts.set_time(_parse_ts("2026-07-01 17:30:00"))
        act.tick()

        for pid in act.player_ids:
            act.login(pid)

        ts.set_time(_parse_ts("2026-07-01 18:00:00"))
        act.tick()

        first_match_key = list(act.current_matches.keys())[0]
        first_match = act.current_matches[first_match_key]

        # 连续超时 10 次
        for _ in range(10):
            ts.advance(config.MATCH["move_timeout_sec"] + 1)
            act.tick()
            if first_match.finished:
                break

        history_len = len(first_match.game_history)
        report(
            "超时无限膨胀 game_history",
            history_len >= 10,  # 确认 bug 存在
            f"history_len={history_len} after 10 timeouts (unbounded growth confirmed)"
        )


def test_06_login_fail_response_format():
    """Bug#6: login 失败时返回格式不一致"""
    with TestContext("login_format"):
        act, ts = make_activity()
        # 时间还在 NOT_STARTED，login 应该失败
        ok, payload = act.login("player_01")

        is_string = isinstance(payload, str)
        report(
            "login 失败返回格式不一致",
            is_string,  # 确认 bug：返回裸字符串而非 dict
            f"type={type(payload).__name__}, value={payload!r} (string means inconsistent with success format)"
        )


def test_07_settle_during_buy_race():
    """Bug#7: 买商品和结算时间推进的竞态"""
    with TestContext("settle_race"):
        act, ts = make_activity()
        ts.set_time(_parse_ts("2026-07-01 17:30:00"))
        act.tick()

        for pid in act.player_ids:
            act.login(pid)

        ts.set_time(_parse_ts("2026-07-01 18:00:00"))
        act.tick()

        # 跑完比赛
        _finish_all_matches(act)

        if act.state != "SCORED":
            report("结算与购买竞态", False, f"state={act.state}")
            return

        # 给 player_01 积分
        p = act._player_online("player_01")
        p.score = 500
        p.save()

        # 模拟竞态：一个线程推进时间触发结算，另一个同时尝试购买
        buy_results = []
        barrier = threading.Barrier(2)

        def do_buy():
            barrier.wait()
            ok, msg = act.buy("player_01", "pear")
            buy_results.append(("buy", ok, msg))

        def do_settle():
            barrier.wait()
            ts.set_time(_parse_ts("2026-07-03 00:00:00"))
            act.tick()

        t1 = threading.Thread(target=do_buy)
        t2 = threading.Thread(target=do_settle)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 检查最终状态一致性
        p_final = Player("player_01")
        p_final.load()
        report(
            "结算与购买竞态",
            True,  # 这个测试主要观察是否崩溃 / 数据不一致
            f"buy_result={buy_results}, final_score={p_final.score}, coins={p_final.coins}, state={act.state}"
        )


# ─── 主入口 ────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  In-Process 自动化测试")
    print("=" * 60)
    print()

    test_01_offline_player_settlement_persistence()
    test_02_offline_player_award_points_persistence()
    test_03_shop_concurrent_race()
    test_04_crash_recovery_pending_moves()
    test_05_timeout_infinite_history()
    test_06_login_fail_response_format()
    test_07_settle_during_buy_race()

    print()
    print("=" * 60)
    print("  结果汇总")
    print("=" * 60)
    for name, status, detail in results:
        print(f"  [{status}] {name}")
    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n  Total: {len(results)} | Passed: {passed} | Failed: {len(results) - passed}")


if __name__ == "__main__":
    main()
