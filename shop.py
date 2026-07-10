import threading

from config import SHOP_ITEMS
from reward import reward

# 商品id -> 剩余量
shop_stock = {}
_shop_lock = threading.Lock()


def init_shop():
    global shop_stock
    for item_id, cfg in SHOP_ITEMS.items():
        shop_stock[item_id] = cfg["stock"]


def buy(player_id, item_id, timesrc, player):
    with _shop_lock:
        if item_id not in SHOP_ITEMS:
            return False, "item not found"
        cfg = SHOP_ITEMS[item_id]
        price = cfg["price"]

        if player.score < price:
            return False, "not enough points"

        stock = shop_stock[item_id]
        if stock is not None and stock <= 0:
            return False, "out of stock"

        limit = cfg["per_user_limit"]
        if limit is not None:
            bought = player.get_buy_count(item_id)
            if bought >= limit:
                return False, "per user limit reached"

        if not player.deduct_score(price):
            return False, "deduct failed"

        stock_decremented = False
        try:
            if stock is not None:
                shop_stock[item_id] -= 1
                stock_decremented = True

            player.record_buy(item_id, 1)
            reward(player_id, cfg["name"], 1, timesrc.now(), player)
        except Exception:
            # 回滚已发生的改动,使整笔购买要么全成要么全不成。
            if stock_decremented:
                shop_stock[item_id] += 1
            # 把扣掉的积分加回来(走统一入口,会落盘)。
            player.score += price
            player.save()
            raise

        return True, f"bought {cfg['name']}"


def to_dict():
    with _shop_lock:
        return {"stock": dict(shop_stock)}


def from_dict(d):
    global shop_stock
    with _shop_lock:
        for item_id in SHOP_ITEMS:
            if item_id not in d["stock"]:
                d["stock"][item_id] = SHOP_ITEMS[item_id]["stock"]
        shop_stock = dict(d["stock"])
