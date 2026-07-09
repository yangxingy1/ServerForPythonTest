# 结算状态 : bool
_settled = False

# 已退梦幻币的玩家集合(仅当 _settled 为真时才有意义)。
# 配合 _settle_all 做崩溃补退:已退的不重发(幂等),未退的可补退。
# 只有全部应退玩家都退完后才把 _settled 置真(BUG-2)。
_refunded = set()


def is_settled():
    return _settled


def mark_refunded(player_id):
    """记录某玩家已退币。幂等。"""
    _refunded.add(player_id)


def is_refunded(player_id):
    return player_id in _refunded


def mark_settled():
    """标记结算完成(全部玩家已退币后调用)。"""
    global _settled
    _settled = True


def to_dict():
    return {
        "settled": _settled,
        "refunded": sorted(_refunded),
    }


def from_dict(d):
    global _settled, _refunded
    _settled = d.get("settled", False)
    _refunded = set(d.get("refunded", []))
