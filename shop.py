from config import SHOP_ITEMS
from reward import reward

# 商品id -> 剩余量
shop_stock = {}


def init_shop():
    global shop_stock
    for item_id, cfg in SHOP_ITEMS.items():
        shop_stock[item_id] = cfg["stock"]


def buy(player_id, item_id, timesrc, player):
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

    if stock is not None:
        shop_stock[item_id] -= 1

    player.record_buy(item_id, 1)
    reward(player_id, cfg["name"], 1, timesrc.now(), player)
    return True, f"bought {cfg['name']}"


def to_dict():
    return {"stock": dict(shop_stock)}


def from_dict(d):
    global shop_stock
    for item_id in SHOP_ITEMS:
        if item_id not in d["stock"]:
            d["stock"][item_id] = SHOP_ITEMS[item_id]["stock"]
    shop_stock = dict(d["stock"])
