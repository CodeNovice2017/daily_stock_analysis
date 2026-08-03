# 涨停余温扫描器（Stock Screener）

> 独立模块，零侵入上游代码。所有代码位于 `src/stock_screener/`。

## 定位

基于「涨停余温战法」的全市场扫描引擎，是 DSA 的二次开发扩展模块。上游项目持续迭代时本模块不会产生 merge 冲突。

## 核心逻辑

### 三条件评估（三选二入围）

| 条件 | 名称 | 规则 | 量化标准 |
|------|------|------|----------|
| 1 | 价格底线 | 3 日收盘价守住涨停价上方 | `close >= 涨停价 × 0.97` |
| 2 | 新高动作 | 资金仍在运作 | `≥2 日盘中创涨停后新高` |
| 3 | 量能控制 | 筹码锁定，非出货 | `3 日均量 ∈ [涨停日量×40%, 涨停日量×100%]`（严格：必须真缩量）|

### 严格模式（宁缺毋滥）

除三条件外，额外两道闸门，贴合「放量是出货」的纪律：

1. **单日放量熔断（一票否决）**：任一后续交易日成交量 > 涨停日量 × 1.2 → 直接淘汰，即便价格守住、新高不断。
   - 对应战法原话：「放量超过120%是分批出货」
   - 由 `LIMIT_UP_SCREENER_VOLUME_SURGE_RATIO` 控制（默认 1.2，设 0 关闭）
2. **均量上限收紧**：3 日均量上限从作者原文的 120% 收到 100%（`LIMIT_UP_SCREENER_VOLUME_HIGH` 默认 1.0），必须真正缩量而非持平/放量。

实测效果：宽松模式下 51 只入围，严格模式只剩 9 只（清一色缩量余温），把 day1 放量 1.43 倍的分歧票全部剔除。

### 评分体系（0-100）

- 每项条件满分 34 分（根据强度浮动）
- 取最佳两项条件分之和作为基础分
- 三项全满足额外加 32 分
- 合格分数线：68-100（满足 ≥2 条件）

### 状态机

```
涨停检测 → detected → (等3交易日) → qualified / failed
                                            ↓
                                      超时 → expired
```

## 用法

```bash
# 手动触发
python -m stock_screener                  # 当日扫描
python -m stock_screener --date 2025-05-30  # 指定日期
python -m stock_screener --no-notify       # 不推送通知
python -m stock_screener --status          # 查看跟踪状态

# 定时任务（crontab）
0 20 * * 1-5 cd /path/to/project && python -m stock_screener
```

## 配置

通过环境变量配置（加到 `.env` 即可），不改上游配置文件：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LIMIT_UP_SCREENER_ENABLED` | false | 总开关 |
| `LIMIT_UP_SCREENER_TRACK_DAYS` | 3 | 涨停后跟踪天数 |
| `LIMIT_UP_SCREENER_PRICE_HOLD_RATIO` | 0.97 | 价格底线比例 |
| `LIMIT_UP_SCREENER_VOLUME_LOW` | 0.40 | 量能下限比例 |
| `LIMIT_UP_SCREENER_VOLUME_HIGH` | 1.0 | 量能上限比例（严格：必须真缩量）|
| `LIMIT_UP_SCREENER_VOLUME_SURGE_RATIO` | 1.2 | 单日放量熔断阈值，超过一票否决（0 关闭）|
| `LIMIT_UP_SCREENER_MIN_CONDITIONS` | 2 | 最少满足条件数（1-3）|
| `LIMIT_UP_SCREENER_MAX_AGE_DAYS` | 10 | 记录过期天数 |

## 模块结构

```
src/stock_screener/
├── __init__.py          # 包声明
├── __main__.py          # CLI 入口（python -m src.stock_screener）
├── config.py            # 自读环境变量，不侵入上游 Config
├── models.py            # ORM + Repository，自建 limit_up_records 表
├── engine.py            # 纯逻辑引擎（无 IO 依赖）
├── holiday.py           # A 股交易日历（holiday-cn）
├── limit_up_sources.py  # 涨停数据源：Tushare 优先 + AKShare 兜底
└── service.py           # 编排服务，复用上游 DataFetcherManager + NotificationService
```

### 依赖的上游能力

| 上游模块 | 用途 | 接入方式 |
|---------|------|---------|
| `data_provider.base.DataFetcherManager` | K线数据 + AKShare 涨停池兜底 | 运行时 import |
| `src.storage.DatabaseManager` | SQLite 连接 | 运行时 import |
| `src.storage.Base` | ORM 基类 | 延迟 import 注册表 |
| `src.notification.NotificationService` | 推送通知 | 运行时 import |
| `src.config.tushare_token` | Tushare 涨停池（优先数据源） | 运行时读取 |

### 涨停数据源

优先级：**Tushare `limit_list_d`** → AKShare `stock_zt_pool_em`（兜底）

- Tushare 需配置 `TUSHARE_TOKEN`（5000 积分档可调用 `limit_list_d`），数据更丰富（连板数、炸板次数、首封/末封时间、流通市值）
- 未配置 token 或 Tushare 失败时自动回退 AKShare（走上游 `DataFetcherManager`）

### 交易日历

基于 [holiday-cn](https://github.com/NateScarlet/holiday-cn) 精确判断 A 股交易日：

- 法定假日数据本地缓存到 `data/stock_screener/holidays/`，首次拉取后离线可用
- `run_daily` 自动把非交易日归一到最近交易日（避免日期错位）
- 评估时按「涨停后 N 个真实交易日」判断是否可评估，而非日历日估算

### 数据库

自动创建 `limit_up_records` 表（复用上游 SQLite），字段：

- 涨停日数据：code, name, limit_up_date, limit_up_price, limit_up_high, limit_up_volume
- 板块信息：industry, consecutive_boards, seal_amount, break_count
- 评估结果：status, cond_price_hold, cond_new_highs, cond_volume, score
- 跟踪明细：day_data_json（JSON 数组）, score_details_json

## 通知格式

Markdown 表格推送到已配置的通知渠道（route_type="alert"）：

```
# 涨停余温扫描 (2025-05-30)

> 检测到 35 只新涨停 | 评估 12 只 | 入围 5 只 | 淘汰 7 只

## 入围股票
| 排名 | 代码 | 名称 | 涨停价 | 行业 | 价格守住 | 新高 | 量能 | 满足 | 评分 |
...

## 跟踪中
| 代码 | 名称 | 涨停日期 | 涨停价 | 连板 | 行业 |
...
```

## 测试

```bash
python -m pytest tests/test_stock_screener.py -v
```

20 个测试覆盖：板块分类、涨停判断、三条件评估（全通过/部分通过/边界值）、评分范围、数据不足处理。

## 后续规划

| 阶段 | 内容 |
|------|------|
| P1 | LLM 软判断：催化剂质量分析、龙虎榜解读、板块共振判断 |
| P2 | Web 展示、T+N 胜率统计、策略参数调优、组合风控 |
| P3 | 港股/美股支持、回测引擎、策略参数自动优化 |
