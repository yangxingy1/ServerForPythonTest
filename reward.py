from datetime import datetime


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def reward(player_id, rtype, amount, ts, player=None):
    # 统一发奖入口：修改玩家内存对象资源 + 落盘 + 打印日志
    if player is not None:
        if rtype == "SCORE":
            player.score += amount
        elif rtype == "梦幻币":
            player.coins += amount
        # 道具发货：rtype 为道具名，只记录不改变 score/coins
        player.rewards.append({
            "type": rtype,
            "amount": amount,
            "ts": _fmt_ts(ts),
        })
        player.save()
    print(f"[REWARD] player={player_id} type={rtype} amount={amount} ts={_fmt_ts(ts)}")
