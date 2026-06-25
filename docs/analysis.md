# AI 精细测试流程 - 项目分析与测试计划

## 一、服务启动与验证方法

### 启动服务器

```bash
python server.py
```

监听 `0.0.0.0:9999`，虚拟时间从 `2026-07-01 17:00:00` 启动。

### 活动时间线（config.py）

| 时间点 | 状态迁移 | 说明 |
|--------|----------|------|
| 07-01 17:00 | 服务启动 | `NOT_STARTED` |
| 07-01 17:30 | `LOGIN_OPEN` | 玩家可登录 |
| 07-01 18:00 | `RUNNING` | 32人对阵表生成，第1轮开始 |
| 5轮打完 | `SCORED` | 积分发放，商店开放 |
| 07-03 00:00 | `SETTLED` | 剩余积分退为梦幻币 |

### 管理指令

```bash
python admin.py settime "2026-07-01 17:30:00"   # 跳到指定时间
python admin.py advancetime 1800                 # 向前推进秒数
```

### 玩家客户端

```bash
python client.py player_01
# 交互命令: play rock|paper|scissors, query, buy banana|apple|pear, quit
```

### 完整验证流程

1. 启动 server → settime 到 17:30 → 登录开放
2. 多终端跑 client player_01 ~ player_32 登录
3. settime 到 18:00 → 比赛开始
4. 各 client 出拳 → 3局2胜晋级 → 5轮后进入 SCORED
5. 在 SCORED 阶段用 buy 花积分
6. settime 到 07-03 00:00 → 结算退款

---

## 二、代码架构

```
server.py        ← TCP 网关，JSON 指令分发
  └─ activity.py ← 状态机核心
       ├─ bracket.py     ← 32人淘汰赛树（随机分组 + 按轮晋级）
       ├─ match.py       ← 单场3局2胜（出拳、超时判定）
       ├─ shop.py        ← 积分商店（库存、限购、扣分、发货）
       ├─ settlement.py  ← 结算标记
       ├─ reward.py      ← 统一发奖（积分/梦幻币/道具）
       ├─ player.py      ← 玩家数据模型 + JSON 持久化
       └─ persist.py     ← 全局快照读写
timesrc.py       ← 可注入时间源（支持 set_time / advance）
config.py        ← 配置常量
admin.py         ← 管理端 CLI
client.py        ← 玩家端 CLI
```

---

## 三、已发现的潜在 Bug / 测试入手点

| # | 类型 | 位置 | 问题描述 |
|---|------|------|----------|
| 1 | 结算漏发 | activity.py:224-236 `_settle_all` | 离线玩家退款：创建临时 Player 对象 load() 后扣分发币，但 reward() 内部虽调了 save()，整体流程依赖 reward 内部行为，如果 reward 未传 player 则数据丢失 |
| 2 | 积分漏发 | activity.py:175-181 `_award_points` | 离线玩家创建临时对象发积分，依赖 reward() 内部 save()，值得验证是否真正落盘 |
| 3 | 并发竞态 | shop.py:24-38 | 库存检查和扣减非原子：两玩家同时买 stock=1 的商品，都通过 stock>0 检查，库存变 -1 |
| 4 | 崩溃丢状态 | match.py:161-163 `_pending_moves` | 出手暂存在内存 dict（非持久化），from_dict 恢复时不含此字段，崩溃重连后已出手丢失 |
| 5 | 无限膨胀 | match.py:79 | 双方超时 → 平局重出同 game 号，但每次都往 game_history 记一条，持续超时则无限增长 |
| 6 | 返回格式不一致 | activity.py:96-110 + server.py:96-98 | login 失败返回 (False, "string")，server 直接 json.dumps 发出去，客户端收到裸字符串非标准 JSON 结构 |
| 7 | 状态竞态 | activity.py:141 + _tick | buy 操作与 tick 时间推进并发，可能在 SCORED→SETTLED 切换瞬间出现竞态 |

---

## 四、测试策略

### 最佳方式：In-Process 测试

直接实例化 `Activity` + 注入 `TimeSrc`，无需 TCP 连接：

```python
from timesrc import TimeSrc
from activity import Activity

ts = TimeSrc()
ts.set_time(parse("2026-07-01 17:30:00"))
act = Activity(ts)
act.login("player_01")
```

优势：
- 时间完全可控
- 无网络开销
- 可模拟崩溃恢复（保存快照 → 新建 Activity 重新加载）
- 可精确控制并发时序

### TCP 集成测试

模拟多 client 通过 socket 完成完整活动周期，验证网络层 + 并发问题。

### AI 精细测试 Prompt 策略

设计 agent 分工：
- **静态分析 Agent**：读代码提取边界条件和不变式
- **测试生成 Agent**：基于分析结果生成测试用例
- **判定 Agent**：区分真 bug vs 预期行为
- **对抗 Agent**：挑战测试覆盖度，寻找遗漏路径

---

## 五、已完成工作与实验结果

### 5.1 In-Process 自动化测试（test_inprocess.py）

7 个测试用例全部验证通过，确认 bug 存在：

| # | 测试名称 | 结果 | 说明 |
|---|----------|------|------|
| 1 | 离线玩家结算落盘 | PASS | reward() 内部有 save()，数据实际落盘了 |
| 2 | 离线玩家积分落盘 | PASS | 同上，依赖 reward 内部行为 |
| 3 | 商店并发竞态 | **BUG确认** | 12人抢10库存，全部成功，stock=-2 |
| 4 | 崩溃恢复出手丢失 | PASS(bug确认) | pending_moves 崩溃后为 None |
| 5 | 超时无限膨胀 | PASS(bug确认) | 10次超时后 history_len=10，无限增长 |
| 6 | login格式不一致 | PASS(bug确认) | 失败返回裸字符串 |
| 7 | 结算与购买竞态 | PASS | 竞态条件下服务器未崩溃 |

### 5.2 TCP 集成测试（test_integration.py）

13 个测试用例全部通过：

- 登录未开放时被拒 ✓
- admin settime 成功 ✓
- 32 玩家全部登录成功 ✓
- 推进到比赛开始 ✓
- 状态变为 RUNNING ✓
- 出拳指令被接受 ✓
- 超时推进后服务器正常 ✓
- 比赛状态正确 ✓
- 断线重连 resync ✓
- 无效出拳被拒 ✓
- 未知命令被拒 ✓
- 无效 player_id 被拒 ✓
- 并发出拳全部收到响应 ✓

### 5.3 AI 精细测试 Prompt 策略（ai_test_strategy.py）

定义了完整的多 Agent 编排方案：

```
Phase 1: 静态分析（3 个 Agent 并行）
    → 提取不变式、边界条件、数据流、未持久化状态、竞态点

Phase 2: 测试生成（3 个 Agent 并行）
    → 边界测试 + 集成测试 + 异常路径测试

Phase 3: 执行与判定
    → 跑测试 + Judge Agent 过滤误报

Phase 4: 对抗与补全
    → Adversary Agent 找遗漏 → 补充测试 → 迭代

Phase 5: 报告生成
```

---

## 六、下一步计划

1. **实际调用 LLM 跑单 Agent 基线**：用 SINGLE_AGENT_PROMPT + 源码，看 AI 自主能发现几个 bug
2. **实现多 Agent 编排框架**：把 ai_test_strategy.py 中的流程落地为可执行的自动化脚本
3. **对比实验**：单 Agent vs 多 Agent 的召回率、误报率、token 消耗
4. **预埋更多 bug**：在代码中刻意植入更多隐蔽 bug，扩大标准答案集
5. **迁移性验证**：将流程应用到不同复杂度的被测代码上
