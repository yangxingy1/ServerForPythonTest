# 32 强猜拳锦标赛服务端 — 接口契约与测试编写指南

> **本文件供自动测试生成 agent 阅读。** 目标是消除"用例与接口不符"类失败。
> 下面每一条"❌ 错误写法 / ✅ 正确写法"都对应过往真实跑挂的用例,**生成用例前务必通读**。
> 黄金法则:**只调用本文件和源码中确实存在的接口,严格按这里写明的返回值结构、容器类型、状态前置条件来断言。拿不准就读源码,不要臆测。**

---

## 1. 系统概览

- 32 人**单败淘汰**猜拳锦标赛,共 **5 轮**:32 → 16 → 8 → 4 → 2 → 1(冠军),全程 **31 场** Match(16+8+4+2+1)。
- 单场 Match 为 **3 局 2 胜**制。
- 活动是**时间驱动状态机**,**没有后台定时器**:状态只在显式调用 `tick()`(或通过 socket 的 `settime`/`advancetime`)时才推进。
- 三类持久化:快照文件(`runtime/snapshot.json`)、玩家文件(`runtime/players/<player_id>.json`),路径由 `config.PERSIST` 配置、测试时可重定向。
- 模块清单:`activity`(核心状态机)、`match`、`bracket`、`shop`、`settlement`、`player`、`reward`、`persist`、`timesrc`、`server`(TCP 入口)、`config`。

> **测试分层建议(重要)**:
> - **端到端(socket / e2e)是回归主力**——跨真实进程与协议、最接近线上,且不耦合任何内部结构,鲁棒性最高。协议一致性、鉴权、状态守卫、关键业务路径优先用 e2e 覆盖。见 §9 的**共享 server fixture**(全程一个进程,杜绝端口争用)。
> - **进程内(inprocess)用于 e2e 测不到的内部不变式**——资金守恒(结算发币、扣分减库存)、崩溃恢复一致性、`_pending_moves` 等内部状态。这类强耦合内部约定,**少而精**即可,严格按 §4/§5/§7/§8 的真实结构写,否则跑到断言前就崩。
> - 状态名只有 `NOT_STARTED / LOGIN_OPEN / RUNNING / SCORED / SETTLED` 五个(见 §5),**没有 `INIT`**;断言状态时用这五个字符串。

---

## 2. 时间字段是字符串,不能直接做数值运算 ⚠️

`config.py` 里所有时间字段都是 **`"YYYY-MM-DD HH:MM:SS"` 格式的字符串**,不是 Unix 时间戳:

```python
TIMELINE = {
    "login_open_ts": "2026-07-01 17:30:00",   # str
    "start_ts":      "2026-07-01 18:00:00",   # str
    "settle_ts":     "2026-07-03 00:00:00",   # str
}
CLOCK = {"boot_ts": "2026-07-01 17:00:00"}    # str
```

而 `TimeSrc.set_time(target_ts: float)` / `advance(seconds: float)` 要求的是**数值时间戳(float)**。

```python
# ❌ 字符串直接运算 / 直接喂给 set_time —— 必报 TypeError: unsupported operand type(s) for -: 'str' and 'int'
ts.set_time(TIMELINE["login_open_ts"] - 10)
ts.set_time(TIMELINE["login_open_ts"])

# ✅ 先转成时间戳。项目里已有现成转换函数,直接复用:
from datetime import datetime
def to_ts(s):  # 与 activity._parse_ts / server._parse_ts 一致
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()

ts.set_time(to_ts(TIMELINE["login_open_ts"]) - 10)
```

`TimeSrc.now()` 返回 `time.time() + _offset`,是 float。任何与时间相关的比较/加减都用 float。

---

## 3. 关键接口的返回值结构(最常被记错)

### 3.1 `Activity.login / play / buy` 返回 **二元组 `(bool, payload)`**,不是 dict

```python
def login(self, player_id) -> tuple   # (ok: bool, payload: dict | str)
def play(self, player_id, move) -> tuple   # (ok: bool, msg: str)
def buy(self, player_id, item_id) -> tuple # (ok: bool, msg: str)
```

```python
# ❌ 当成 dict 用 —— 必报 AttributeError: 'tuple' object has no attribute 'get'
resp = act.login("player_01")
assert resp.get("status") == "ok"

# ✅ 先解包
ok, payload = act.login("player_01")
assert ok is True
# 成功时 payload 是 dict:
#   有进行中对局 -> {"event": "resync", "round":..., "opponent":..., ...}
#   无进行中对局 -> {"event": "ok", "state": <当前状态>}
# 失败时 payload 是 str(错误原因),如 "login not open yet" / "invalid player_id"
```

`query(player_id)` 是例外——它直接返回 dict:`{"state":..., "score":..., "current_round":...}`。

### 3.2 socket 响应字段是 **`event`**,不是 `status`

`server.Server._dispatch` 返回的 JSON 统一用 `event` 键,取值 `"ok"` / `"error"` / `"resync"`,外加 `msg`:

```python
# ❌ 断言不存在的 "status" 字段
assert resp["status"] == "ok"
# ✅
assert resp["event"] in ("ok", "error", "resync")
```

---

## 4. 容器类型:`current_matches` 是 dict,迭代出的是 key(int)

```python
self.current_matches = {}   # dict: {match_index(int) -> Match}
self.players = {}           # dict: {player_id(str) -> Player}  仅在线玩家
self.logged_in = set()      # set: {player_id(str)}
```

```python
# ❌ 把 current_matches 当成 Match 的可迭代集合 —— 报 AttributeError: 'int' object has no attribute 'finished'
for m in act.current_matches:
    if not m.finished: ...

# ✅ dict 要取 .values() 才是 Match 对象
for m in act.current_matches.values():
    if not m.finished: ...
# 或按 index 取: m = act.current_matches[0]
```

注意各轮对局数量:**第 1 轮有 16 场**(32/2),不是 1 场。别假设 `len(current_matches) == 1`。

---

## 5. 状态机推进:进 SCORED 必须打完全部 5 轮 ⚠️

状态严格单调前进:`NOT_STARTED → LOGIN_OPEN → RUNNING → SCORED → SETTLED`。各转移的**真实前置条件**:

| 目标状态 | 触发方式 | 前置条件 |
|---|---|---|
| LOGIN_OPEN | `tick()` | `now >= login_open_ts` |
| RUNNING | `tick()` | `now >= start_ts`(自动 `init_bracket` + 开始第 1 轮) |
| SCORED | `play()` 或超时,使**第 5 轮(决赛)最后一场 Match 结束** | 必须逐轮打完 32→16→8→4→2→1 |
| SETTLED | `tick()` | 当前是 SCORED 且 `now >= settle_ts` |

```python
# ❌ 以为打几局 / 推一次时间就能进 SCORED —— 实际仍是 RUNNING,断言失败
ts.set_time(to_ts(TIMELINE["start_ts"])); act.tick()
# ...打了两局...
assert act.state == "SCORED"   # AssertionError: 'RUNNING' == 'SCORED'
```

**进入 SCORED 需要把整棵赛程打完**。猜拳判定规则:`rock>scissors`、`scissors>paper`、`paper>rock`;平局重出。让某方稳赢:其出 `rock`、对手出 `scissors`,重复 2 局即胜一场。完整推进需循环每一轮的每一场喂出手直到 `act.state` 变为 `SCORED`。**这是开销很大的集成剧本,断言状态前先确认确实驱动到位**(可用 `act.state` / `act.current_round` 实时检查,而不是假设)。

如果只想测 SCORED/SETTLED 而不想真打完 5 轮,**优先用崩溃恢复路径构造**:手工写一份 `state="SCORED"` 的快照落盘,再新建 `Activity(ts)` 触发 `_try_restore` 恢复到该状态(见 §8)。

---

## 6. 登录有状态前置:NOT_STARTED 下 login 必失败

```python
def login(self, player_id):
    if player_id not in self.player_ids:      # 合法 id 为 "player_01".."player_32"
        return False, "invalid player_id"
    if self.state == self.STATE_NOT_STARTED:  # 未开放登录直接失败,不加入 logged_in
        return False, "login not open yet"
    ...
```

```python
# ❌ 没把状态推到 LOGIN_OPEN 就 login,然后断言已登录 —— logged_in 仍为空集
act = Activity(ts)            # 此刻 state=NOT_STARTED
act.login("player_01")
assert "player_01" in act.logged_in   # AssertionError: in set()

# ✅ 先驱动到 LOGIN_OPEN(或 RUNNING)再 login
ts.set_time(to_ts(TIMELINE["login_open_ts"])); act.tick()   # -> LOGIN_OPEN
ok, _ = act.login("player_01")
assert ok and "player_01" in act.logged_in
```

**合法 `player_id` 只有 32 个固定值,且必须是两位零填充字符串**:`"player_01"`、`"player_02"` …… `"player_09"`、`"player_10"` …… `"player_32"`。
由 `activity.py` 中 `[f"player_{i:02d}" for i in range(1, 33)]` 生成,任何其它写法都会被 `login` 以 `"invalid player_id"` 拒绝,或在 `act.players[...]` / `bracket.slots` 里 KeyError。

```python
# ❌ 这些全是非法 id,过往真实跑挂:
"p1", "p00", "tester", "alice", "e2e_player", "nonexistent", 1
"player_0", "player_1", "player_5"        # 少一位零填充也非法! 必须 "player_01"/"player_05"
# ✅ 唯一正确格式(两位零填充):
"player_01", "player_05", "player_32"
# 需要遍历全部玩家时,直接复用生成规则:
player_ids = [f"player_{i:02d}" for i in range(1, 33)]
```

---

## 7. `Match._pending_moves` 是惰性创建的,出手前不存在 ⚠️

`_pending_moves` 用来暂存当局出手,**只在第一次调用 `_set_move`(即有人 `play`)时才被创建**,且**不写进 `to_dict()`**(已知设计:崩溃重建后丢失当局出手):

```python
def _set_move(self, player_id, move):
    if not hasattr(self, "_pending_moves"):   # 惰性创建
        self._pending_moves = {}
    self._pending_moves[player_id] = move
```

```python
# ❌ 出手前直接访问 —— 报 AttributeError: 'Match' object has no attribute '_pending_moves'
m = Match(ts, 1, 0, 1, 2, "player_01", "player_02")
assert m._pending_moves != {}

# ✅ 正确姿势:
#  - 想验证"出手被暂存": 先 m.start() 再 m.play(pid, move),然后用 getattr 兜底
m.start(); m.play("player_01", "rock")
assert getattr(m, "_pending_moves", {}).get("player_01") == "rock"
#  - 想验证"序列化不含该字段(已知丢失 bug)": 断言它【不在】to_dict() 结果里
assert "_pending_moves" not in m.to_dict()
```

`Match.to_dict()` 实际包含的字段:`round_num, match_index, slot_a, slot_b, player_a, player_b, wins, current_game, current_mover, move_deadline, game_history, finished, winner`。`Match.from_dict(d, timesrc)` 是 **classmethod**,需要传 `timesrc`。

---

## 8. 故障注入 / 隔离上下文

每个用例必须隔离持久化路径 + 重置三处模块级全局状态,否则测试间相互污染:

```python
import os, tempfile, shutil
import config, persist, shop as shop_mod, settlement as settlement_mod

class Env:
    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        self._old = dict(config.PERSIST)
        config.PERSIST["snapshot_path"]   = os.path.join(self.tmp, "snapshot.json")
        config.PERSIST["player_data_dir"] = os.path.join(self.tmp, "players")
        persist._snapshot = {}              # 模块级全局,必须重置
        shop_mod.shop_stock = {}            # 模块级全局,必须重置
        settlement_mod._settled = False     # 模块级全局,必须重置
        return self
    def __exit__(self, *a):
        config.PERSIST.clear(); config.PERSIST.update(self._old)
        shutil.rmtree(self.tmp, ignore_errors=True)
```

- **崩溃恢复**:驱动到某状态(会自动 `_save_full` 落盘)→ 丢弃 `act` → 新建 `Activity(ts)`,构造时自动调 `_try_restore` 从快照恢复 → 断言恢复后的 `state / current_round / bracket / shop_stock / settlement` 与崩溃前一致。`_pending_moves` 除外(必然丢失)。

### 8.1 手写快照注入:必须严格按各 section 的真实结构 ⚠️

"手写快照再 `Activity(ts)` 恢复"是构造 SCORED/SETTLED 的省力捷径,但 `_try_restore` 会把每个 section 喂给对应模块的 `from_dict`,**结构写错会在构造 `Activity` 时就崩**(过往真实失败:`KeyError: 'stock'`、`'list' object has no attribute 'items'`)。

每个 section 的**精确结构**(用 `persist.save_snapshot(section, data)` 逐段写入):

| section | 类型 | 结构 / 示例 | 易错点 |
|---|---|---|---|
| `"state"` | str | `"SCORED"` | 必须是合法状态名,无 `"INIT"` |
| `"logged_in"` | list[str] | `["player_01", "player_02"]` | 是 list 不是 set |
| `"current_round"` | int | `5` | |
| `"bracket"` | dict | `{"slots": {"1": "player_07", ...}, "round_winners": {"1": {"0": 3, ...}}}` | `slots`/`round_winners` 都是 **dict**(JSON key 为字符串);**不是 list**。`slots` 必须 32 项 |
| `"shop"` | dict | `{"stock": {"banana": 10, "apple": 30, "pear": null}}` | 外层必须包一层 `{"stock": {...}}`,不能直接 `{"banana":10}` |
| `"settlement"` | dict | `{"settled": false}` | key 是 `"settled"` |
| `"matches"` | dict | `{"0": <Match.to_dict()>, ...}` | key 是字符串化的 match_index;空可填 `{}` |

```python
# ✅ 构造一个 SCORED 状态(空对局、商店满库存)的最小快照:
import persist
def inject_scored_snapshot(player_ids):
    persist.save_snapshot("state", "SCORED")
    persist.save_snapshot("logged_in", [])
    persist.save_snapshot("current_round", 5)
    persist.save_snapshot("bracket", {
        "slots": {str(i + 1): player_ids[i] for i in range(32)},  # 32 项, key 为字符串
        "round_winners": {},
    })
    persist.save_snapshot("shop", {"stock": {"banana": 10, "apple": 30, "pear": None}})
    persist.save_snapshot("settlement", {"settled": False})
    persist.save_snapshot("matches", {})
# 之后 act = Activity(ts) 会自动 _try_restore 到 SCORED
```

> 注:`_try_restore` 末尾会调一次 `_tick()`。若注入 SCORED 且 `now >= settle_ts`,会立刻迁到 SETTLED。要停在 SCORED,先 `ts.set_time(to_ts(TIMELINE["start_ts"]))`(早于 settle_ts)。
> **更稳的替代**:如果只是想验证某接口在 SCORED 下的行为,优先考虑用端到端(socket)流程或真实驱动,手写快照容易与内部结构耦合出错。

---

## 9. E2E(socket)用例:端口写死 9999,不要换端口 ⚠️

`server.py` **端口硬编码为 9999**,且从 `sys.argv[1]` 读 `boot_ts`(日期字符串)。它没有提供改端口的入口。**端到端(socket)是本项目的回归主力**:它跨真实进程与协议、最接近线上,且不依赖任何内部结构约定(快照/容器/状态名),鲁棒性最高。请优先把协议类(protocol)与关键业务路径用 e2e 覆盖。

**核心纪律:全程只用一个 server 进程,固定 9999,所有 e2e 用例共享它。** 端口写死无法并行,**每个用例各起一个 server 会互相抢 9999**,导致后启的连不上(`ConnectionRefused`)或前一个残留把连接踢掉(`ConnectionReset`)——这正是过往 4 个 e2e 全挂的根因。正确做法是用一个 **module 级 fixture** 起一次、跑完所有 e2e 再关:

```python
# ✅ 放进 imports: 整个测试模块共享同一个 server,杜绝端口争用
import subprocess, socket, json, time, sys, pytest
PORT = 9999

def _wait_port(timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=0.3); s.close(); return True
        except OSError:
            time.sleep(0.1)
    return False

@pytest.fixture(scope="module")
def server():
    # cwd 默认就是被测项目根(stage5 已设),server.py 用相对路径 runtime/
    p = subprocess.Popen([sys.executable, "server.py", "2026-07-01 17:00:00"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert _wait_port(), "server 未在 10s 内就绪"
    yield p
    p.terminate()
    try: p.wait(timeout=5)
    except Exception: p.kill()

def send_cmd(obj):
    """每条指令用一个短连接发送并读一行响应。失败原因也在 event 字段里,不要假设连接保持。"""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=3)
    try:
        s.sendall((json.dumps(obj) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.split(b"\n")[0].decode())
    finally:
        s.close()

# 每个 e2e 用例都把 server 作为参数注入(触发共享 fixture),不要自起进程:
def test_e2e_query_returns_dict(server):
    resp = send_cmd({"cmd": "query", "player_id": "player_01"})
    assert isinstance(resp, dict) and "event" in resp or "state" in resp
```

> 注意:e2e 用例之间共享同一个 server 进程 = **共享同一份活动状态**(时间、登录、对局)。用例顺序会相互影响,设计时要么让每个用例自洽(用 `settime` 把时间推到所需阶段),要么不依赖其它用例的残留状态。这是真实进程级测试的固有代价,换来的是最接近线上的可信度。

socket 指令格式(每行一条 JSON):
- `{"cmd":"login","player_id":"player_01"}`
- `{"cmd":"play","player_id":"player_01","move":"rock"}`
- `{"cmd":"buy","player_id":"player_01","item":"apple"}`
- `{"cmd":"query","player_id":"player_01"}`
- `{"cmd":"settime","ts":"2026-07-01 18:00:00","token":"admin-secret-token"}`(管理指令,`ts` 是**日期字符串**)
- `{"cmd":"advancetime","seconds":3600,"token":"admin-secret-token"}`

管理指令(`settime`/`advancetime`)必须带正确 `token`(见 `config.ADMIN["token"]` = `"admin-secret-token"`);token 错误返回 `{"event":"error","msg":"unauthorized"}` 且不改时间/状态。

---

## 10. 各模块接口签名速查(以此为准)

> 标注 `(self,...)` 的是**实例方法**:必须先构造实例再调,如 `Player("player_01").load()`,**不能** `Player.load("player_01")`。
> 标注 `@classmethod` 的可直接 `Cls.method(...)`。其余为模块级函数。

```text
[config]  常量(无函数): TIMELINE/CLOCK(时间字段均为 str), MATCH, SHOP_ITEMS, REFUND, PERSIST, ADMIN

[timesrc] class TimeSrc:
    __init__(self)                 # 不带时间参数,初始 offset=0
    now(self) -> float
    set_time(self, target_ts: float)   # 参数是 float 时间戳,不是字符串
    advance(self, seconds: float)

[player]  class Player:
    __init__(self, player_id)      # player_id 形如 "player_01"
    load(self)                     # 实例方法! 从盘加载;文件不存在则创建。无返回值
    save(self)
    add_win(self)
    record_buy(self, item_id, count)
    get_buy_count(self, item_id) -> int
    deduct_score(self, amount) -> bool   # 余额不足返回 False,不扣
    to_dict(self) -> dict
    # 字段: score, coins, buys(dict), rewards(list), wins

[match]   class Match:
    __init__(self, timesrc, round_num, match_index, slot_a, slot_b, player_a, player_b)
    start(self)
    play(self, player_id, move) -> (bool, str)   # move ∈ {"rock","paper","scissors"}
    check_timeout(self) -> bool
    get_state_for_player(self, player_id) -> dict
    to_dict(self) -> dict
    from_dict(cls, d, timesrc) -> Match          # @classmethod, 需传 timesrc
    # _pending_moves 惰性创建、不序列化(见 §7)

[bracket] class Bracket:
    __init__(self)
    init_bracket(self, player_ids, seed=None)
    get_matchups(self, round_num) -> list[tuple]   # [(slot_a, slot_b, player_a, player_b), ...]
    record_winner(self, round_num, match_index, winner_slot)
    get_champion_slot(self) -> int | None
    get_champion(self) -> str | None
    get_player_wins(self, player_id) -> int
    to_dict(self) -> dict
    from_dict(cls, d) -> Bracket                   # @classmethod

[shop]    模块级函数 + 模块级全局 shop_stock(dict, 测试间必须重置):
    init_shop()                                    # 按 SHOP_ITEMS 重填库存
    buy(player_id, item_id, timesrc, player) -> (bool, str)   # 注意参数顺序与类型
    to_dict() -> dict        # {"stock": {...}}
    from_dict(d)

[settlement] 模块级函数 + 模块级全局 _settled(bool, 测试间必须重置):
    is_settled() -> bool
    to_dict() -> dict        # {"settled": bool}
    from_dict(d)

[persist] 模块级函数 + 模块级全局 _snapshot(dict, 测试间必须重置):
    save_snapshot(section, data)        # 注意是 (section_name, data) 两个参数
    load_snapshot() -> dict             # 无参数; 读盘并返回整个快照 dict
    get_snapshot_section(section) -> any
    # 没有名为 load() 的函数,不要调用 persist.load(...)

[reward]  模块级函数:
    reward(player_id, rtype, amount, ts, player=None)
    # rtype="SCORE" 加 score; rtype="梦幻币" 加 coins; 其它视为道具只记录

[activity] class Activity:
    __init__(self, timesrc)            # 构造时自动 init_shop + _try_restore
    login(self, player_id) -> (bool, dict|str)     # 见 §3.1
    logout(self, player_id)
    query(self, player_id) -> dict                 # 直接返回 dict
    play(self, player_id, move) -> (bool, str)
    buy(self, player_id, item_id) -> (bool, str)
    tick(self)                                      # 推进状态机
    # 字段: state(str), players(dict), logged_in(set),
    #       bracket(Bracket), current_round(int), current_matches(dict{int:Match})
    # 状态常量: STATE_NOT_STARTED/LOGIN_OPEN/RUNNING/SCORED/SETTLED

[server]  class Server:
    __init__(self, host="0.0.0.0", port=9999, boot_ts_str=None)
    start(self)                        # 阻塞监听; 测试用 subprocess 起,固定端口 9999
    # 响应 JSON 用 "event" 键(见 §3.2),不是 "status"
```

---

## 11. 已知设计缺陷(测试时按"已知行为"对待,别误判为可修复 bug)

- `Match._pending_moves` 不持久化:崩溃重建后当局出手丢失(§7)。
- `settlement._settled = True` 先于 `_save_full` 落盘:崩溃重建可重复结算发币(资金安全窗口)。
- `shop.buy` 扣分与减库存之间无原子保证:中途崩溃可能积分已扣但库存未减。

测试这些不变式时,应**断言系统是否有保护**,而非假设字段一定存在或一定被恢复。

---

## 12. 生成用例前的自检清单

1. 时间字段先经 `to_ts()` 转 float 了吗?没有直接拿 `TIMELINE[...]` 做减法?
2. `login/play/buy` 的返回值解包成 `(ok, payload)` 了吗?没有对元组调 `.get()`?
3. 遍历 `current_matches` 用了 `.values()` 吗?没有把 int 当 Match?
4. 断言状态前确实驱动到位了吗?状态名只用 `NOT_STARTED/LOGIN_OPEN/RUNNING/SCORED/SETTLED` 五个,**没有 `INIT`**?
5. `login` 前状态已是 LOGIN_OPEN/RUNNING 吗?`player_id` 是两位零填充的 `"player_01"`(不是 `"player_1"`/`"p1"`/`"alice"`)吗?
6. 访问 `_pending_moves` 前已 `play` 过、或用了 `getattr` 兜底吗?
7. **手写快照注入**时,每个 section 结构对吗?`shop` 包了 `{"stock":{...}}`、`bracket.slots` 是 32 项 dict(非 list)?(见 §8.1)
8. **E2E 用例共享同一个 module 级 server fixture** 吗?没有每个用例各起一个 server 抢 9999?管理指令带 token、`ts` 是日期字符串吗?
9. 实例方法(如 `Player.load`)先构造实例再调了吗?
10. 每个进程内用例都进了 `Env` 隔离上下文、重置了三处全局状态吗?
