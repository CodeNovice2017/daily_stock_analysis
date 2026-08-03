# 盘中自动追踪系统设计文档

**日期**: 2026-05-24
**状态**: 待实现
**模块**: `src/intraday/` + `intraday_main.py`

---

## 1. 背景与目标

现有 `daily_stock_analysis` 系统覆盖了日线级别的分析、AI研判、多渠道通知。但缺少盘中实时监控能力：无法在交易时间内追踪持仓股异动、捕捉买卖时机、保护已有利润。

本模块补足盘中分析能力，核心原则：**不瞎分析，每个信号都要有历史胜率验证。**

### 1.1 核心价值

不是"发现牛股"，而是"管理持仓"：
1. **保护利润** — 涨到压力位时提醒减仓
2. **捕捉加仓时机** — 急跌到支撑位+放量时提醒
3. **避免追高** — 缩量涨到压力位时提醒别加仓

### 1.2 设计约束

- 作为现有项目的独立模块，复用已有基础设施（数据层、通知层、LLM层）
- 信号必须有回测验证胜率，胜率不达标的信号不推送
- 盘中监控和日线分析生命周期独立运行

---

## 2. 架构方案：半独立模块

在现有项目内新增 `src/intraday/` 目录 + 独立入口 `intraday_main.py`。

- **独立进程**：盘中监控需要持续运行4小时，与日线分析的一次性运行天然不同
- **复用基础设施**：import 复用 `data_provider/`、`Config`、`notification_sender/`、`agent/llm_adapter`
- **共享配置**：同一个 `.env`，盘中专用参数统一使用 `INTRADAY_` 前缀

### 2.1 选择理由

- 紧集成方案会耦合不同生命周期，增加维护负担
- 完全独立服务会导致大量重复代码（数据源、通知、LLM）
- 半独立模块在复用和独立之间取得平衡

---

## 3. 模块结构

```
daily_stock_analysis/
├── main.py                        # 现有日线分析入口（不动）
├── intraday_main.py               # 新增：盘中监控入口
├── src/intraday/                  # 新增：盘中监控核心模块
│   ├── __init__.py
│   ├── config.py                  # 盘中专属配置（继承主Config，扩展INTRADAY_*参数）
│   ├── scheduler.py               # 盘中调度器（交易时间判断、15分钟轮询）
│   ├── data_fetcher.py            # 5分钟K线+实时行情+资金流向获取
│   ├── signal_engine.py           # 信号检测引擎（注册+检测+分级）
│   ├── signals/                   # 具体信号实现
│   │   ├── __init__.py
│   │   ├── base.py                # 信号基类（定义统一接口）
│   │   ├── volume_breakout.py     # 放量突破
│   │   ├── panic_drop.py          # 急跌放量
│   │   ├── chip_breakout.py       # 筹码位突破
│   │   ├── macd_volume.py         # MACD金叉+放量
│   │   ├── support_break.py       # 支撑破位
│   │   ├── low_volume.py          # 缩量蓄势（中信号）
│   │   ├── big_order.py           # 大单异动（中信号）
│   │   └── sector_resonance.py    # 板块共振（中信号）
│   ├── backtest/                  # 回测引擎
│   │   ├── __init__.py
│   │   ├── engine.py              # 回测执行器
│   │   ├── loader.py              # 历史5分钟K线加载（Tushare缓存到SQLite）
│   │   └── reporter.py            # 回测结果统计+报告
│   ├── ai_analyzer.py             # LLM综合分析（信号→操作建议）
│   ├── evolution.py               # 自我进化（每日复盘+信号权重调整）
│   ├── store.py                   # 信号记录持久化（SQLite，独立表）
│   └── notifier.py                # 盘中推送（复用现有notification_sender）
├── strategies/intraday/           # 新增：盘中专用LLM策略YAML
│   ├── intraday_sector_alert.yaml # 板块异动策略
│   └── intraday_event_alert.yaml  # 事件驱动策略
```

### 3.1 入口与执行参数

`intraday_main.py` 所有执行参数使用 `intraday-` 前缀，防止与主项目冲突：

```bash
python intraday_main.py --intraday-backtest                        # 回测全部信号
python intraday_main.py --intraday-backtest --signal volume_breakout  # 回测特定信号
python intraday_main.py --intraday-monitor                         # 盘中监控模式
python intraday_main.py --intraday-evolve                          # 收盘复盘模式
```

---

## 4. 数据层

### 4.1 数据源

主力数据源为 Tushare Pro（用户积分5000，可访问分钟级数据）。复用现有 `data_provider/tushare_fetcher.py`。

| 数据类型 | Tushare 接口 | 获取频率 |
|---------|-------------|---------|
| 5分钟K线（历史+实时） | `stk_mins` (5min) | 每15分钟拉取最新；回测时批量拉取过去1年 |
| 实时行情快照 | `rt_k` / `rt_min` | 信号触发时补充查询 |
| 资金流向（大单净流入） | `moneyflow` | 每15分钟（同K线轮询） |
| 筹码分布 | `cyq_chips` / `cyq_perf` | 每日开盘前拉取一次 + 价格触发时刷新 |

### 4.2 被监控股票

独立于日线分析的 `STOCK_LIST`，使用 `INTRADAY_WATCH_LIST` 环境变量配置。范围通常比日线分析更广（自选股范围）。

### 4.3 调度节奏

```
09:15  开盘前准备：拉取筹码分布、昨日K线、MA/支撑位计算
09:30  开始监控
09:45  第1次轮询（5分钟K线 + 资金流向）
10:00  第2次轮询
       ...每15分钟一次
11:30  午间休市（暂停轮询）
13:00  下午开盘，恢复轮询
       ...每15分钟一次
14:45  最后一次轮询
15:00  收盘，触发复盘（--intraday-evolve）
15:30  推送每日复盘报告
```

### 4.4 数据缓存

- 当日5分钟K线缓存在内存（pandas DataFrame），每15分钟追加更新
- 历史K线（回测用）缓存到本地SQLite，避免重复拉取
- 调用量估算：每次轮询 N只股票 x 2个接口，15分钟间隔，远低于Tushare 80次/分钟限制

---

## 5. 信号检测层：双轨架构

### 5.1 设计理念

复用现有项目的策略生态（15个YAML策略 + SkillManager/SkillRouter/SkillAgent），采用量化信号 + LLM策略信号双轨并行。

### 5.2 量化信号轨道（纯Python计算）

每个信号实现统一接口：

```python
class BaseSignal(ABC):
    name: str
    level: SignalLevel  # STRONG / MEDIUM / WEAK

    @abstractmethod
    def detect(self, df: pd.DataFrame, context: SignalContext) -> Optional[SignalResult]:
        """
        df: 最近N根5分钟K线（至少20根）
        context: 包含资金流向、筹码分布、MA值等辅助数据
        返回: SignalResult 或 None（未触发）
        """
        ...
```

#### 5个强信号定义

| 信号名 | 输入 | 触发条件 | 输出 |
|-------|------|---------|------|
| 放量突破 | 20根5min K线 | 量比>3（当前量/20根均量）且 close > max(high_1..high_20) | 突破价位、量比倍数 |
| 急跌放量 | 5根5min K线 | 最近1根: 跌幅>2% 且 量>均量x5 且 close!=跌停价 | 急跌幅度、量比倍数 |
| 筹码突破 | 20根K线 + 筹码数据 | close > cost_95（90%筹码上沿）且 当日累计量 > 5日均量x1.5 | 突破的筹码位、放量程度 |
| MACD金叉+放量 | 40根K线（算MACD） | MACD柱由负转正 且 当日量>5日均量x1.5 | MACD值、放量倍数 |
| 支撑破位 | 20根K线 + 日线MA | close < min(MA20, MA60, 前低) 且 当前量>均量x2 | 跌破的支撑位、放量程度 |

#### 3个中信号定义

| 信号名 | 触发条件 | 用途 |
|-------|---------|------|
| 缩量蓄势 | 连续1小时振幅<1% + 成交量萎缩至均量50%以下 | 可能变盘前兆 |
| 大单异动 | 5分钟内大单净流入>前1小时总净流入x3 | 主力可能动作 |
| 板块共振 | 同板块>=3只股票同时出现相同方向异动 | 板块轮动信号 |

### 5.3 LLM策略信号轨道（复用现有Skill体系）

- 新增 `strategies/intraday/` 目录存放盘中专用策略YAML
- 复用 `SkillManager` 加载、`SkillRouter` 路由、`SkillAgent` 执行
- 复用 `data_tools` 中的 `get_realtime_quote`、`get_chip_distribution`、`get_capital_flow` 等工具
- LLM策略信号触发方式：量化信号命中后作为补充深度分析，或特定事件（板块集体异动）时触发

### 5.4 检测流程

```
每15分钟轮询:
1. 拉取最新K线数据
2. 量化信号检测（毫秒级，确定性）:
   for each stock:
       for each quant_signal:
           result = signal.detect(df, context)
           if result: 记录 → 判断是否需要LLM深度分析
3. LLM策略信号（秒级，上下文理解）:
   if 强信号触发:
       触发SkillRouter选择匹配策略
       SkillAgent执行深度分析
       输出signal + confidence
4. 合并输出统一 SignalResult
```

### 5.5 扩展机制

- **新增量化信号**：在 `signals/` 下新建文件，实现 `BaseSignal.detect()`，自动注册
- **新增LLM信号**：在 `strategies/intraday/` 下新建YAML，自动被 SkillManager 加载

### 5.6 去重机制

同一信号对同一只股票，当日只触发一次（避免反复推送）。

---

## 6. 回测框架

### 6.1 自建轻量回测引擎

需求是"信号命中率统计"，不是完整的模拟交易系统。自建更轻量可控。

### 6.2 回测流程

```
1. loader.py: 批量拉取历史5分钟K线（Tushare stk_mins），缓存到SQLite
2. engine.py:
   for each trading_day in range(回测天数):
       for each 5min_bar in trading_day:
           for each quant_signal in signals:
               result = signal.detect(bar_context)
               if result:
                   记录: 触发时间、触发价格
                   计算: 信号后30min/60min/1day的涨跌幅
3. reporter.py:
   汇总每个信号的: 胜率 / 平均收益 / 最大亏损 / 触发次数
   输出: 信号有效性报告（保留>55%的，淘汰<50%的）
```

### 6.3 LLM信号回测

LLM策略信号的回测复用现有项目的 `BacktestEngine`（已有NLP方向推断+前向收益评估机制），不新建。

---

## 7. AI分析层

### 7.1 触发时机

量化强信号触发后，调用LLM做综合判断。中信号不触发LLM分析，仅记录。

### 7.2 输入构造

```
├── 触发的信号类型和具体数据（突破价位、量比、跌幅等）
├── 该股票的持仓成本和仓位（从INTRADAY_PORTFOLIO配置读取）
├── 近5日走势摘要（从K线数据生成）
├── 当前板块状态（领涨/领跌/震荡）
├── 大盘环境（上证/创业板当日涨跌）
└── 相关新闻（可选，复用现有SearchService）
```

### 7.3 输出格式

```json
{
  "action": "BUY | SELL | HOLD | WATCH",
  "target_price": 63.50,
  "position_ratio": 0.30,
  "confidence": 7,
  "reasoning": "放量突破前高且MACD金叉确认，板块整体走强+1.2%",
  "risk_warning": "注意64.50附近为前期密集成交区"
}
```

### 7.4 LLM调用

复用现有 `LLMAdapter` / LiteLLM Router，直接 import，不重新封装。

---

## 8. 自我进化层

### 8.1 每日收盘复盘（--intraday-evolve）

```
1. 回放当日所有信号记录（从SQLite读）
2. 对比实际走势:
   - 强信号触发后60分钟实际涨跌 → 更新信号胜率
   - LLM操作建议 vs 实际走势 → 更新LLM准确率
3. 动态调整:
   - 连续5天胜率<50%的信号 → 降级（强→中/中→弱）
   - 连续10天胜率<50%的信号 → 暂停
   - 胜率>60%的信号 → 升级
4. 生成每日复盘报告 → Telegram推送
5. 每周日汇总周报 → 信号有效性排名
```

### 8.2 信号权重持久化

信号胜率、权重、等级变更记录存储在SQLite中，跨日持久化。

---

## 9. 通知

### 9.1 推送渠道

复用现有 `notification_sender/telegram_sender.py`，通过 `INTRADAY_NOTIFICATION_CHANNELS` 独立配置推送通道。

### 9.2 推送场景

| 场景 | 推送方式 | 频率 |
|------|---------|------|
| 强信号触发 | Telegram 即时推送 | 实时（交易时间内） |
| 中信号记录 | 收盘复盘报告中汇总 | 每日一次 |
| 每日收盘复盘 | Telegram 自动推送 | 15:30 |
| 每周信号报告 | Telegram + 文件 | 周末 |

### 9.3 消息格式

```
🔴 强信号 - 通富微电(002156)
────────────────────
信号：放量突破
时间：10:45
突破价：62.35（前高61.80）
量比：3.8倍
────────────────────
AI建议：加仓
目标价位：63.50-64.00
建议仓位：加至总仓位30%
信心度：7/10
理由：放量突破前高且MACD金叉确认，
     板块（半导体）今日整体走强+1.2%
风险：注意64.50附近为前期密集成交区
```

---

## 10. 配置项

所有盘中专用配置统一使用 `INTRADAY_` 前缀，新增到 `.env`：

```env
# === 盘中监控配置 ===
INTRADAY_WATCH_LIST=002156.SZ,600460.SH,600887.SH   # 盘中监控股票列表
INTRADAY_POLL_INTERVAL=15                              # 轮询间隔（分钟）
INTRADAY_NOTIFICATION_CHANNELS=telegram                # 盘中推送通道
INTRADAY_LLM_MODEL=                                    # 空=复用主LLM配置
INTRADAY_BACKTEST_DAYS=365                             # 回测天数
INTRADAY_STRONG_THRESHOLD=55                           # 强信号胜率阈值(%)
INTRADAY_EVOLVE_COOLDOWN=5                             # 连续N天低于阈值才降级
INTRADAY_PORTFOLIO=002156.SZ:62.00:1000,600460.SH:28.50:2000  # 持仓：代码:成本:数量
```

---

## 11. 建设路线图

### Phase 1: 信号回测验证（Week 1-2）

1. 搭建 `src/intraday/` 基础框架：config、data_fetcher、signal_engine、信号基类
2. 实现 `backtest/loader.py`：历史5分钟K线拉取+缓存
3. 实现5个强信号的 `detect()` 逻辑
4. 实现 `backtest/engine.py`：回测执行器
5. 实现 `backtest/reporter.py`：胜率统计报告
6. 跑回测，淘汰胜率<50%的信号

### Phase 2: 盘中监控上线 — 模拟盘（Week 3-4）

7. 实现 `scheduler.py`：交易时间调度、15分钟轮询
8. 实现 `store.py`：信号记录SQLite持久化
9. 实现 `notifier.py`：复用Telegram推送
10. 实现 `intraday_main.py --intraday-monitor` 模式
11. 信号触发时推送（标注"模拟盘"）
12. 收盘自动复盘 + 信号命中率统计

### Phase 3: AI分析层接入（Week 5-6）

13. 实现 `ai_analyzer.py`：信号→LLM prompt构造→结构化输出
14. 实现 `evolution.py`：每日复盘+信号权重动态调整
15. 实现 `intraday_main.py --intraday-evolve` 模式
16. 对比LLM建议 vs 实际执行效果
17. 建立自我反思循环

### Phase 4: LLM策略信号 + 持续优化（Week 7+）

18. 新增 `strategies/intraday/` 策略YAML
19. 实现LLM策略信号与量化信号的融合
20. 逐步增加信号种类
21. 探索多角色架构（参考TradingAgents）

---

## 12. 参考项目

| 项目 | 路径 | 参考价值 |
|------|------|---------|
| AxiomEdge-PRO | `/home/chase/projects/reference/AxiomEdge-PRO/` | LLM策略师+持久记忆+自动失败恢复架构 |
| QuantBacktest | `/home/chase/projects/reference/QuantBacktest/` | 事件驱动回测框架设计思路 |
| TradingAgents | `/home/chase/projects/reference/tradingagents/` | 多Agent协作+LangGraph编排模式 |
