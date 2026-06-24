"""
AI 精细测试流程 - Prompt 策略与多 Agent 编排方案

本文件定义了让 AI 自主发现边界/集成/异常路径 bug 的 prompt 模板和 agent 分工。
可直接作为后续自动化框架的配置输入。
"""

# ─── 单 Agent 基线方案 ──────────────────────────────────────

SINGLE_AGENT_PROMPT = """
你是一位资深游戏服务器测试工程师。你的任务是对以下 Python 游戏活动服务器进行深度测试，
目标是找到 **边界条件、跨模块集成、异常恢复路径** 中的 bug，而非仅仅测试正常流程。

## 被测系统概述

这是一个 32 人猜拳淘汰赛活动服务器，包含：
- 活动状态机：NOT_STARTED → LOGIN_OPEN → RUNNING → SCORED → SETTLED
- 淘汰赛：32 人随机分组，5 轮 3 局 2 胜制
- 积分商店：胜场换积分，积分买道具（有库存限制、个人限购）
- 结算退款：活动结束时剩余积分按比例退为梦幻币
- 崩溃恢复：通过 JSON 快照持久化，支持进程重启后恢复状态
- 时间驱动：可注入时间源，支持 set_time / advance 跳时间

## 测试重点方向

请从以下维度深度测试，每个维度至少给出 3-5 个具体测试用例：

### 1. 边界条件
- 时间恰好在状态切换点的行为（如恰好在 settle_ts 时买商品）
- 库存为 1 时的并发购买
- 积分恰好等于价格时购买后再次操作
- 超时时间精确边界（deadline 前 1ms vs 后 1ms）
- 32 人中有人不登录时比赛如何处理

### 2. 跨模块集成
- 积分发放 → 商店购买 → 结算退款的完整链路数据一致性
- 离线玩家的积分发放是否正确落盘
- bracket 晋级结果与 player.wins 计数是否一致
- reward 模块对 score/coins/道具三种类型的处理是否统一

### 3. 异常路径与崩溃恢复
- 玩家出拳后、结果判定前进程崩溃（pending_moves 是否持久化）
- 比赛中途玩家断线重连，状态同步是否正确
- 结算过程中崩溃，重启后是否会重复退款
- 快照文件损坏时的恢复行为

### 4. 并发与竞态
- 两个玩家同时买最后一个库存商品
- 同一玩家同时发送两次出拳请求
- tick() 触发状态迁移时，另一个线程正在处理 buy/play 请求

## 输出格式

对每个测试用例，输出：
```
## 用例名称
- 类型: [边界/集成/异常/并发]
- 前置条件: ...
- 测试步骤: 1. ... 2. ... 3. ...
- 预期结果: ...
- 实际风险: 描述如果有 bug 会导致什么后果
```
"""


# ─── 多 Agent 编排方案 ─────────────────────────────────────

AGENT_ROLES = {
    "analyzer": {
        "name": "静态分析 Agent",
        "description": "阅读源码，提取不变式、边界条件、状态转移约束",
        "prompt": """
你是一位代码静态分析专家。阅读以下游戏活动服务器的完整代码，提取：

1. **不变式（Invariants）**：系统在任何时刻必须满足的约束
   例如：player.score >= 0、shop_stock[item] >= 0、settlement 只能发生一次

2. **状态转移约束**：每个状态只能转移到特定的下一个状态

3. **边界条件**：哪些数值参数处于边界时可能出问题
   例如：stock=1, per_user_limit 刚好用完, score 刚好等于 price

4. **跨模块数据流**：哪些数据在多个模块间传递，每一步是否有可能丢失或不一致

5. **未持久化的关键状态**：哪些内存中的状态没有被 snapshot 保存

输出为结构化的 JSON：
```json
{
  "invariants": [{"description": "...", "location": "file:line", "risk": "high/medium/low"}],
  "state_transitions": [...],
  "boundary_conditions": [...],
  "data_flows": [...],
  "unpersisted_states": [...]
}
```
""",
    },

    "test_generator": {
        "name": "测试生成 Agent",
        "description": "基于分析结果生成可执行的 Python 测试代码",
        "prompt": """
你是一位测试代码生成专家。基于静态分析 Agent 的发现，为每个风险点生成可执行的 Python 测试。

## 约束
- 使用 in-process 测试方式（直接实例化 Activity + TimeSrc）
- 每个测试函数独立，使用 TestContext 隔离运行时目录
- 测试必须有明确的 assert 判定，不能只是"跑一遍看看"
- 优先覆盖 risk=high 的不变式违反场景

## 测试模板
```python
def test_xxx():
    with TestContext("xxx"):
        act, ts = make_activity()
        # 设置前置条件
        ts.set_time(...)
        act.tick()
        # 执行操作
        ...
        # 断言：验证不变式是否被违反
        assert condition, "描述预期 vs 实际"
```

## 来自分析 Agent 的发现
{analyzer_output}

请为每个 high/medium 风险点生成测试代码。
""",
    },

    "judge": {
        "name": "判定 Agent",
        "description": "审查测试结果，区分真 bug vs 预期行为 vs 误报",
        "prompt": """
你是一位测试结果判定专家。你的任务是审查测试结果，判断：

1. **真 Bug**：代码行为违反了合理的业务预期
2. **设计如此**：代码行为虽然意外，但是有意为之的设计决策
3. **误报**：测试本身的逻辑有问题

## 判定依据
- 数据不一致（数据库中的值 vs 内存中的值 vs 预期值）一定是 bug
- 状态丢失（崩溃后恢复不了）一定是 bug
- 负数库存一定是 bug
- 重复发奖一定是 bug
- 如果某个行为只在并发下出现，仍然算 bug（线上就是并发的）

## 测试结果
{test_results}

请逐条判定，输出：
```json
[
  {"test_name": "...", "verdict": "bug|design|false_positive", "confidence": 0.9, "reasoning": "..."}
]
```
""",
    },

    "adversary": {
        "name": "对抗 Agent",
        "description": "挑战已有测试的覆盖度，寻找遗漏的测试路径",
        "prompt": """
你是一位测试对抗专家（Devil's Advocate）。你的任务是审查当前的测试套件，找出：

1. **遗漏的测试路径**：哪些代码路径完全没被测试到
2. **不够深的测试**：哪些测试只测了表面，没有深入到极端情况
3. **组合爆炸的遗漏**：哪些状态组合没被覆盖（例如：断线 + 超时 + 最后一轮）

## 思考方式
- 对每个模块，问"如果这里出错，现有测试能抓到吗？"
- 对每个数据流，问"这条链路中间断了会怎样？"
- 对每个状态转移，问"如果时序错了会怎样？"

## 当前测试覆盖
{current_tests}

## 源代码
{source_code}

输出格式：
```json
[
  {
    "gap": "描述遗漏",
    "risk_level": "high/medium/low",
    "suggested_test": "简述如何测试这个 gap",
    "why_missed": "为什么之前的测试没覆盖到"
  }
]
```
""",
    },
}


# ─── 编排流程 ─────────────────────────────────────────────

ORCHESTRATION_PIPELINE = """
多 Agent 精细测试编排流程
=========================

Phase 1: 静态分析（并行）
    ┌─ Analyzer Agent A: 聚焦"不变式 + 边界条件"
    ├─ Analyzer Agent B: 聚焦"跨模块数据流 + 未持久化状态"
    └─ Analyzer Agent C: 聚焦"并发竞态点 + 状态机转移"

Phase 2: 测试生成（依赖 Phase 1）
    ┌─ Test Generator A: 针对边界条件生成测试
    ├─ Test Generator B: 针对集成/数据流生成测试
    └─ Test Generator C: 针对异常路径/崩溃恢复生成测试

Phase 3: 执行与判定（依赖 Phase 2）
    ├─ 执行所有生成的测试
    └─ Judge Agent: 判定每个失败是真 bug 还是误报

Phase 4: 对抗与补全（依赖 Phase 3）
    ├─ Adversary Agent: 审查覆盖度，找遗漏
    └─ 补充测试 → 回到 Phase 3 迭代

Phase 5: 报告生成
    └─ 汇总所有确认的 bug，按类型/严重度分类，输出最终报告
"""


# ─── 评估指标 ─────────────────────────────────────────────

EVALUATION_METRICS = """
## 召回率计算方法

预埋 Bug 清单（标准答案）：
- 每个 bug 标记类型：边界 / 集成 / 异常 / 并发
- 每个 bug 标记难度：easy / medium / hard

召回率 = 被正确识别的 bug 数 / 预埋 bug 总数

分维度召回率：
- 边界条件召回率
- 集成问题召回率
- 异常路径召回率
- 并发竞态召回率

对比指标：
- 单 Agent 召回率 vs 多 Agent 召回率
- 单 Agent 误报率 vs 多 Agent 误报率
- 单 Agent 耗时 vs 多 Agent 耗时（token 消耗）

## 预埋 Bug 参考（基于代码分析已发现的）

| # | 类型 | 难度 | 描述 |
|---|------|------|------|
| 1 | 集成 | medium | 离线玩家结算退款依赖 reward() 内部 save |
| 2 | 集成 | medium | 离线玩家积分发放同上 |
| 3 | 并发 | easy | 商店库存非原子扣减，可超卖至负数 |
| 4 | 异常 | hard | pending_moves 未持久化，崩溃后出手丢失 |
| 5 | 边界 | medium | 双方超时无限重试，game_history 无限膨胀 |
| 6 | 集成 | easy | login 失败返回裸字符串，格式不一致 |
| 7 | 并发 | medium | buy 与 tick 状态迁移的竞态 |
"""


# ─── 快速验证：单 Agent 基线测试执行器 ────────────────────

def run_single_agent_baseline():
    """
    模拟单 Agent 测试流程：
    1. 将 SINGLE_AGENT_PROMPT + 代码 发送给 LLM
    2. 获取返回的测试用例
    3. 执行测试
    4. 判定结果
    """
    print("=" * 60)
    print("  单 Agent 基线方案")
    print("=" * 60)
    print()
    print("流程：")
    print("  1. 发送 SINGLE_AGENT_PROMPT + 全部源码给 LLM")
    print("  2. LLM 返回测试用例列表")
    print("  3. 将用例转为可执行的 Python 测试")
    print("  4. 执行并收集结果")
    print("  5. 对照预埋 bug 清单计算召回率")
    print()
    print("预期输出：")
    print("  - 测试用例数量")
    print("  - 覆盖的 bug 类型分布")
    print("  - 召回率")
    print("  - 误报率")


def run_multi_agent_pipeline():
    """
    模拟多 Agent 编排流程：
    Phase 1-5 按顺序执行，每阶段输出传给下一阶段
    """
    print("=" * 60)
    print("  多 Agent 编排方案")
    print("=" * 60)
    print()
    print(ORCHESTRATION_PIPELINE)
    print()
    print("对比维度：")
    print("  - 多 Agent 是否发现了单 Agent 遗漏的 bug")
    print("  - 多 Agent 的误报率是否更低（有 Judge Agent 过滤）")
    print("  - 多 Agent 的对抗环节是否补全了覆盖空白")


if __name__ == "__main__":
    run_single_agent_baseline()
    print()
    run_multi_agent_pipeline()
    print()
    print(EVALUATION_METRICS)
