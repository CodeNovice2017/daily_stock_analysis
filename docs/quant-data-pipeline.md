# 量化数据管线 & 盘中监控模块 — 开发复盘

> 2026-05-31 编写，记录盘中分析（intraday）和量化数据管线（quant_data）两个半独立模块的设计决策、实现状态、参考来源和待办事项。

## 一、模块定位

| 模块 | 目录 | 入口 | 职责 |
|------|------|------|------|
| 盘中监控 | `src/intraday/` | `intraday_main.py` | 盘中 15 分钟轮询，5 个信号检测，通知推送 |
| 量化数据管线 | `src/quant_data/` | `quant_data_main.py` | 批量拉取历史数据（日 K、分钟 K、资金流等），Parquet + DuckDB 存储 |
| 选股器 | `src/stock_screener/` | `python -m src.stock_screener` | 涨停/连板/首板筛选（与上述两个模块并列） |

三个模块均为**半独立模块**：有独立的 CLI 入口、独立配置段（.env `QUANT_*` / `INTRADAY_*`），不侵入主流程（`main.py`、`server.py`）。

## 二、量化数据管线（quant_data）

### 2.1 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 存储格式 | Parquet + DuckDB | 列式存储，ZSTD 压缩比 ~10:1；DuckDB 嵌入式无需部署，直接查询 Parquet 文件 |
| 分区策略 | Hive-style（`symbol=XXX/year=YYYY` 或 `date=YYYYMMDD`） | 按股票分区保证单票查询高效，日度数据按天分区天然幂等 |
| 数值精度 | float32（价格）、float64（成交额/市值） | A 股价格最多 6 位小数，float32 省 50% 空间 |
| 压缩 | ZSTD level 3 | 压缩比与速度的最佳平衡 |
| 元数据 | DuckDB 文件记录水位线 | 借鉴 zer0share MetaStore，增量从 `last_date+1` 开始 |

### 2.2 数据源

| 数据源 | 免费额度 | 拉取内容 | 实现模块 |
|--------|---------|---------|---------|
| **BaoStock** | 免费，QPS ~20 | 5/15/30/60 分钟 K 线（1990-至今） | `baostock_downloader.py` |
| **Tushare Pro** (5000 积分) | 500 calls/min | moneyflow（资金流向）、daily_basic（估值指标）、cyq_chips（筹码分布） | `tushare_downloader.py` |
| **SimTradeData** 开源数据包 | 免费 | 日 K、估值、基本面、复权信息（历史快照） | `import_simtradedata.py` |

> 注：Tushare 的分钟线（`stk_mins`）需额外 2000 元/年，因此分钟数据走 BaoStock。

### 2.3 文件结构

```
src/quant_data/
    __init__.py
    config.py                  # QuantDataConfig 独立单例，从 .env 加载
    types.py                   # DownloadTask, DownloadResult, DownloadStatus
    parquet_store.py           # Parquet 读写 + Hive 分区
    meta_store.py              # DuckDB 水位线元数据
    progress.py                # JSON 断点续传（BaoStock 全量下载）
    resilience.py              # @retry 装饰器 + RateLimiter 限流
    stock_list.py              # A 股列表（Parquet 元数据 或 BaoStock）
    baostock_downloader.py     # 分钟 K 线批量下载
    tushare_downloader.py      # Tushare moneyflow/daily_basic/cyq_chips
    duckdb_query.py            # DuckDB SQL 查询层（自动注册视图）
    scheduler.py               # 日度调度器
    import_simtradedata.py     # 导入 SimTradeData .tar.gz 归档

data/quant/                    # Parquet 数据湖
    kline_daily/symbol=XXX/data.parquet       # 日 K（已导入）
    valuation/symbol=XXX/data.parquet          # 估值（已导入）
    fundamentals/symbol=XXX/data.parquet       # 基本面（已导入）
    exrights/symbol=XXX/data.parquet           # 复权（已导入）
    metadata/stock_metadata/data.parquet       # 股票列表
    metadata/trade_days/data.parquet           # 交易日历
    _meta/sync_meta.duckdb                     # 水位线元数据
    kline_5min/symbol=XXX/year=YYYY/data.parquet  # [待下载]
    moneyflow/date=YYYYMMDD/data.parquet           # [待下载]
    daily_basic/date=YYYYMMDD/data.parquet         # [待下载]
    cyq_chips/date=YYYYMMDD/data.parquet           # [待下载]
```

### 2.4 CLI 命令

```bash
# 查看数据湖状态
python quant_data_main.py --quant-status

# SQL 查询（DuckDB）
python quant_data_main.py --quant-query "SELECT * FROM kline_daily LIMIT 10"

# 导入 SimTradeData 归档
python quant_data_main.py --quant-import-archive /path/to/simtradelab-data-cn.tar.gz

# 下载 BaoStock 分钟 K 线（全量或单票）
python quant_data_main.py --quant-download-kline --symbol 600519.SS --start-date 2024-01-01
python quant_data_main.py --quant-download-kline --resume  # 全量断点续传

# 拉取 Tushare 日度数据
python quant_data_main.py --quant-pull-daily --date 20260530

# Tushare 历史回填
python quant_data_main.py --quant-pull-backfill --interface moneyflow --start-year 2020

# 启动日度调度
python quant_data_main.py --quant-schedule --time 18:30
```

### 2.5 当前数据量（2026-05-31 快照）

| 数据集 | 文件数 | 行数 | 大小 | 来源 |
|--------|--------|------|------|------|
| kline_daily | 5,515 | 17,750,015 | 649.8 MB | SimTradeData 导入 |
| valuation | 5,432 | 10,935,315 | 647.6 MB | SimTradeData 导入 |
| fundamentals | 5,434 | 191,600 | 115.5 MB | SimTradeData 导入 |
| exrights | 5,404 | 55,135 | 32.3 MB | SimTradeData 导入 |
| metadata | 3 | 16,934 | 0.2 MB | SimTradeData 导入 |
| **合计** | **~21,788** | **~28.9M** | **~1.4 GB** | |

### 2.6 借鉴的开源项目

| 项目 | 借鉴点 |
|------|--------|
| **SimTradeData** (kay-ou/SimTradeData) | BaoStock 全局会话 + 引用计数；四层韧性（retry + circuit breaker + cooldown + monitor）；进程锁 `fcntl.flock` |
| **zer0share** (zer0coldai/zer0share) | MetaStore 水位线追踪；列名常量模式；Hive glob 查询 `read_parquet(hive_partitioning=true)`；跳过已存在分区 |
| **OSkhQuant** (khscience/OSkhQuant) | 仅作为未来量化策略参考，未借鉴代码 |

三个项目已 clone 至 `/home/chase/projects/stock/references/`。

### 2.7 测试覆盖

| 测试文件 | 测试数 | 覆盖内容 |
|---------|--------|---------|
| `tests/test_quant_data_parquet.py` | 14 | ParquetStore 读写、MetaStore 水位线、ProgressTracker 断点续传 |
| `tests/test_quant_data_baostock.py` | 7 | 年分片、K 线标准化、DuckDB 查询（含真实数据） |
| `tests/test_quant_data_tushare.py` | 14 | HTTP mock、三种接口拉取、跳过已有、回填、水位线推进 |
| `tests/test_quant_data_scheduler.py` | 2 | 调度委托、默认日期 |
| `tests/test_quant_data_config.py` | 5 | 默认值、冻结、单例、环境变量覆盖 |
| **合计** | **42** | 全部通过 |

## 三、盘中监控模块（intraday）

### 3.1 架构

```
盘中 15 分钟轮询 → DataFetcher 取分钟数据 → SignalEngine 分发
                                                    ↓
                                            5 个信号并行检测
                                            (macd_volume / volume_breakout /
                                             chip_breakout / support_break / panic_drop)
                                                    ↓
                                            触发 → IntradaySignalStore 持久化
                                                    ↓
                                            Notifier 推送通知
```

### 3.2 信号列表

| 信号 | 文件 | 触发条件 | 依赖数据 |
|------|------|---------|---------|
| MACD 量价背离 | `signals/macd_volume.py` | MACD 背离 + 成交量放大 | close, volume, avg_daily_volume |
| 放量突破 | `signals/volume_breakout.py` | 成交量 3x + 突破 20 根 K 线新高 | close, high, volume |
| 筹码突破 | `signals/chip_breakout.py` | 价格突破 95% 筹码峰 | close, volume, chip_cost_95 |
| 支撑跌破 | `signals/support_break.py` | 放量跌破 MA20/MA60/前低 | close, volume, ma20, ma60, prev_low |
| 恐慌杀跌 | `signals/panic_drop.py` | 单根 K 线跌 >2% + 量能 5x | close, open, volume |

### 3.3 回测引擎

`backtest/` 子目录提供了历史回测能力：
- `BacktestEngine` — 将历史 5 分钟 K 线逐根喂入信号引擎
- `BacktestLoader` — 从 Parquet 加载历史数据
- `BacktestReporter` — 生成回测报告（胜率、盈亏比、最大回撤）

### 3.4 当前限制

1. **SignalContext 始终为空** — 调度器创建 `SignalContext(ts_code=xxx)` 时，ma20/ma60/chip_cost_95 等字段全为 0。需要从 DuckDB 日 K 数据填充。
2. **分钟数据 API 未接通** — `IntradayDataFetcher` 调用 `TushareFetcher.get_minute_data()`，但该方法尚未实现。
3. **列名不一致** — 信号期望 `df["vol"]`，数据源返回 `df["volume"]`。

## 四、对原项目的侵入性

### 4.1 改动范围

| 类型 | 文件 | 改动方式 |
|------|------|---------|
| 新建 | `src/quant_data/` (13 文件) | 全新目录 |
| 新建 | `src/intraday/` (18 文件) | 全新目录 |
| 新建 | `src/stock_screener/` (7 文件) | 全新目录 |
| 新建 | `quant_data_main.py`, `intraday_main.py` | 独立 CLI 入口 |
| 新建 | 10 个测试文件 | `tests/test_quant_data_*.py`、`tests/test_intraday_*.py` |
| 追加 | `requirements.txt` | 末尾加 2 行（duckdb, pyarrow） |
| 追加 | `.env.example` | 末尾加 22 行（QUANT_* 配置段） |
| 未改 | `main.py`, `server.py`, `src/config.py` | 零改动 |
| 未改 | `.github/workflows/`, `docker/`, `scripts/` | 零改动 |

### 4.2 耦合关系

```
quant_data  ──→  src.config (parse_env_int, parse_env_float, get_config)   [只读]
intraday    ──→  src.config, src.notification.NotificationService          [只读]
stock_screener ──→ src.storage, src.notification                           [只读]

原项目模块 ──→  quant_data / intraday                                      [无]
```

**结论：** 耦合严格单向。原项目的 `main.py`、`server.py`、CI 工作流均不感知这三个新模块。上游更新时，唯一可能冲突的是 `requirements.txt` 和 `.env.example` 的末尾追加位置，属文本级别冲突，解决成本极低。

## 五、待办事项

### 5.1 数据拉取（优先级最高）

- [ ] **运行 BaoStock 5 分钟 K 线下载** — `python quant_data_main.py --quant-download-kline --resume`
  - 预计耗时：数小时（5,500+ stocks × 5 年）
  - 断点续传已实现，中断后可继续
- [ ] **运行 Tushare moneyflow 回填** — `python quant_data_main.py --quant-pull-backfill --interface moneyflow --start-year 2020`
- [ ] **运行 Tushare daily_basic 回填** — `python quant_data_main.py --quant-pull-backfill --interface daily_basic --start-year 2020`
- [ ] **运行 Tushare cyq_chips 回填** — 同上
- [ ] **启动日度调度** — `python quant_data_main.py --quant-schedule --time 18:30`（建议 crontab 或 systemd 管理）

### 5.2 盘中模块补全

- [ ] **SignalContext 填充** — 从 DuckDB 日 K 数据计算 ma20/ma60/prev_low/avg_daily_volume，从 moneyflow 取资金净流入，从 cyq_chips 取筹码峰
- [ ] **分钟数据 API** — 实现 `TushareFetcher.get_minute_data()` 或改走 BaoStock 路径
- [ ] **列名对齐** — 统一信号与数据源的列名约定（`vol` vs `volume`）
- [ ] **分钟级技术指标** — 添加 MACD/RSI/VWAP 等计算能力

### 5.3 长期方向

- 量化策略回测框架（利用已有 `backtest/` + Parquet 分钟数据）
- 批量选股扫描（利用 DuckDB 批量查询能力）
- 可能需要引入 `pandas-ta` 或 `ta-lib` 用于技术指标计算

## 六、新增依赖

```
# requirements.txt 末尾追加
duckdb>=0.10.0              # 嵌入式列式分析引擎
pyarrow>=14.0.0             # Parquet 文件读写
```

已有的 `baostock`、`tushare`、`sqlalchemy`、`requests` 等未重复添加。

## 七、新增环境变量

```env
# .env.example 末尾追加段
QUANT_DATA_DIR=./data/quant
QUANT_BS_START_DATE=2020-01-01
QUANT_BS_FREQUENCY=5
QUANT_BS_BATCH_SIZE=50
QUANT_BS_SLEEP_BETWEEN=0.5
QUANT_BS_MAX_WORKERS=4
QUANT_TUSHARE_INTERFACES=moneyflow,daily_basic
QUANT_TUSHARE_RATE_LIMIT=400
QUANT_PARQUET_COMPRESSION=zstd
QUANT_DUCKDB_MEMORY_LIMIT=2GB
```
