TIMELINE = {
    "login_open_ts": "2026-07-01 17:30:00",
    "start_ts":      "2026-07-01 18:00:00",
    "settle_ts":     "2026-07-03 00:00:00",
}

CLOCK = {
    "boot_ts": "2026-07-01 17:00:00",
}

MATCH = {
    "move_timeout_sec": 60,
    "score_per_win": 100,
}

SHOP_ITEMS = {
    "banana": {"name": "香蕉", "price": 100, "per_user_limit": 1,    "stock": 10},
    "apple":  {"name": "苹果", "price": 50,  "per_user_limit": 2,    "stock": 30},
    "pear":   {"name": "雪梨", "price": 20,  "per_user_limit": None, "stock": None},
}

REFUND = {
    "point_to_coin_ratio": 1.0,  # 1 积分 = 1 梦幻币
}

PERSIST = {
    "snapshot_path": "runtime/snapshot.json",
    "player_data_dir": "runtime/players",
}

ADMIN = {
    "token": "admin-secret-token",
}
