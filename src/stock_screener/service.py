# -*- coding: utf-8 -*-
"""
涨停余温扫描器服务。

独立模块入口，通过 python -m stock_screener 调用。
复用上游 DataFetcherManager + NotificationService，不修改上游代码。
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src.stock_screener.config import ScreenerConfig
from src.stock_screener.engine import (
    LimitUpReference,
    TrackingDay,
    classify_board,
    evaluate,
    is_limit_up,
)
from src.stock_screener.models import LimitUpRepository, ensure_table

logger = logging.getLogger(__name__)


class ScreenerService:
    """涨停余温扫描器：编排检测、评估、通知。"""

    def __init__(self):
        self.config = ScreenerConfig.from_env()
        ensure_table()
        self.repo = LimitUpRepository()
        self._data_manager = None

    @property
    def data_manager(self):
        if self._data_manager is None:
            from data_provider.base import DataFetcherManager
            self._data_manager = DataFetcherManager()
        return self._data_manager

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def run_daily(
        self,
        target_date: Optional[date] = None,
        send_notification: bool = True,
    ) -> Dict[str, Any]:
        """执行完整日扫描：检测新涨停 + 评估已有跟踪 + 通知。"""
        from src.stock_screener.holiday import latest_trading_day_on_or_before, is_trading_day

        raw_date = target_date or date.today()
        # 归一到最近交易日：非交易日扫描会拿到上个交易日的涨停数据，
        # 若按原日期入库会导致日期错位。统一用最近交易日作为 scan_date。
        scan_date = latest_trading_day_on_or_before(raw_date)
        if scan_date != raw_date:
            logger.info("%s 非交易日，归一到最近交易日 %s", raw_date, scan_date)
        stats: Dict[str, Any] = {
            "scan_date": scan_date.isoformat(),
            "detected": 0,
            "evaluated": 0,
            "qualified": 0,
            "failed": 0,
            "expired": 0,
            "errors": 0,
        }

        # 1. 检测新涨停
        try:
            detect_stats = self._detect_new_limit_ups(scan_date)
            stats["detected"] = detect_stats.get("new", 0)
        except Exception as e:
            logger.error("涨停检测失败: %s", e)
            stats["errors"] += 1

        # 2. 评估已有跟踪记录
        try:
            eval_stats = self._evaluate_tracking(scan_date)
            stats["evaluated"] = eval_stats.get("evaluated", 0)
            stats["qualified"] = eval_stats.get("qualified", 0)
            stats["failed"] = eval_stats.get("failed", 0)
        except Exception as e:
            logger.error("余温评估失败: %s", e)
            stats["errors"] += 1

        # 3. 清理过期记录
        try:
            expired = self.repo.expire_stale_records(max_age_days=self.config.max_age_days)
            stats["expired"] = expired
        except Exception as e:
            logger.warning("清理过期记录失败: %s", e)

        # 4. 通知
        if send_notification:
            try:
                self._send_report(scan_date, stats)
            except Exception as e:
                logger.error("通知发送失败: %s", e)
                stats["errors"] += 1

        logger.info(
            "涨停余温扫描完成: date=%s detected=%d evaluated=%d qualified=%d failed=%d expired=%d",
            scan_date, stats["detected"], stats["evaluated"],
            stats["qualified"], stats["failed"], stats["expired"],
        )
        return stats

    def print_status(self):
        """打印当前跟踪状态摘要。"""
        counts = self.repo.count_by_status()
        qualified = self.repo.get_qualified_records(limit=10)
        tracking = self.repo.get_recent_records(days=7, limit=20)
        tracking_active = [r for r in tracking if r.status == "detected"]

        print("=== 涨停余温跟踪状态 ===")
        for status, count in sorted(counts.items()):
            print(f"  {status}: {count}")

        if qualified:
            print(f"\n--- 最近入围 ({len(qualified)}) ---")
            for r in qualified:
                print(f"  {r.code} {r.name or ''} | 涨停价 {r.limit_up_price:.2f} | 评分 {r.score:.0f}")

        if tracking_active:
            print(f"\n--- 跟踪中 ({len(tracking_active)}) ---")
            for r in tracking_active[:10]:
                print(f"  {r.code} {r.name or ''} | 涨停日 {r.limit_up_date}")

    # ------------------------------------------------------------------
    # 检测新涨停
    # ------------------------------------------------------------------

    def _detect_new_limit_ups(self, scan_date: date) -> Dict[str, int]:
        dm = self.data_manager
        date_str = scan_date.strftime("%Y%m%d")

        logger.info("获取涨停池: %s", date_str)
        from src.stock_screener.limit_up_sources import fetch_limit_up_pool
        pool = fetch_limit_up_pool(scan_date, n=200)
        if not pool:
            logger.info("涨停池为空（可能非交易日或无涨停股）")
            return {"scanned": 0, "new": 0, "skipped": 0}

        new_count = 0
        skipped = 0
        for item in pool:
            code = str(item.get("code", "")).strip()
            if not code:
                continue

            pct = item.get("change_pct") or 0
            if not is_limit_up(pct, code=code):
                skipped += 1
                continue

            price = item.get("price") or 0
            if price <= 0:
                skipped += 1
                continue

            # 补充涨停日 high / volume
            limit_high = price
            limit_volume = 0.0
            try:
                df, _ = dm.get_daily_data(code, days=20)
                if df is not None and not df.empty:
                    day_row = df[df["date"] == scan_date.isoformat()]
                    if day_row.empty:
                        day_row = df.tail(1)
                    if not day_row.empty:
                        row = day_row.iloc[0]
                        limit_high = float(row.get("high", price))
                        limit_volume = float(row.get("volume", 0))
            except Exception as e:
                logger.debug("获取 %s K线补充数据失败: %s", code, e)

            try:
                self.repo.upsert_record(
                    code=code,
                    limit_up_date=scan_date,
                    name=item.get("name"),
                    limit_up_price=price,
                    limit_up_high=limit_high,
                    limit_up_volume=limit_volume,
                    limit_up_pct=pct,
                    limit_up_amount=item.get("amount"),
                    consecutive_boards=item.get("consecutive_boards", 1) or 1,
                    industry=item.get("industry"),
                    seal_amount=item.get("seal_amount"),
                    break_count=item.get("break_count", 0) or 0,
                    first_limit_time=item.get("first_limit_time"),
                )
                new_count += 1
            except Exception as e:
                logger.debug("入库 %s 失败: %s", code, e)

        logger.info("涨停检测: scanned=%d new=%d skipped=%d", len(pool), new_count, skipped)
        return {"scanned": len(pool), "new": new_count, "skipped": skipped}

    # ------------------------------------------------------------------
    # 评估跟踪记录
    # ------------------------------------------------------------------

    def _evaluate_tracking(self, scan_date: date) -> Dict[str, int]:
        cfg = self.config
        from src.stock_screener.holiday import is_target_evaluable

        records = self.repo.get_tracking_records(reference_date=scan_date)
        if not records:
            logger.info("无待评估的跟踪记录")
            return {"evaluated": 0, "qualified": 0, "failed": 0}

        dm = self.data_manager
        qualified_count = 0
        failed_count = 0
        skipped_pending = 0

        for record in records:
            try:
                # 用交易日历精确判断：涨停后是否已凑够 track_days 个交易日
                if not is_target_evaluable(record.limit_up_date, cfg.track_days, as_of=scan_date):
                    skipped_pending += 1
                    continue
                result = self._evaluate_one(record, scan_date, dm)
                if result is None:
                    continue
                if result.qualified:
                    qualified_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.warning("评估 %s 失败: %s", record.code, e)

        logger.info(
            "评估完成: total=%d qualified=%d failed=%d pending=%d",
            len(records), qualified_count, failed_count, skipped_pending,
        )
        return {
            "evaluated": len(records),
            "qualified": qualified_count,
            "failed": failed_count,
            "pending": skipped_pending,
        }

    def _evaluate_one(self, record, scan_date: date, dm):
        cfg = self.config
        if not record.limit_up_volume or record.limit_up_volume <= 0:
            logger.debug("跳过 %s: 涨停日成交量缺失", record.code)
            return None

        try:
            df, _ = dm.get_daily_data(record.code, days=30)
        except Exception as e:
            logger.debug("获取 %s K线失败: %s", record.code, e)
            return None

        if df is None or df.empty:
            return None

        lu_date_str = record.limit_up_date.isoformat()
        post_rows = df[df["date"] > lu_date_str].head(cfg.track_days)

        if len(post_rows) < cfg.track_days:
            logger.debug("跳过 %s: 仅有 %d/%d 天后续数据", record.code, len(post_rows), cfg.track_days)
            return None

        tracking_days = []
        day_data = []
        for _, row in post_rows.iterrows():
            td = TrackingDay(
                date=str(row["date"]),
                close=float(row["close"]),
                high=float(row["high"]),
                volume=float(row["volume"]),
            )
            tracking_days.append(td)
            day_data.append({"date": td.date, "close": td.close, "high": td.high, "volume": td.volume})

        ref = LimitUpReference(
            close=record.limit_up_price,
            high=record.limit_up_high or record.limit_up_price,
            volume=record.limit_up_volume,
            price_floor_ratio=cfg.price_hold_ratio,
            volume_low_ratio=cfg.volume_low,
            volume_high_ratio=cfg.volume_high,
            min_conditions=cfg.min_conditions,
            volume_surge_ratio=cfg.volume_surge_ratio,
        )

        result = evaluate(ref, tracking_days, expected_days=cfg.track_days)

        score_details = {
            "conditions": [
                {"name": c.name, "passed": c.passed, "score": c.score, "details": c.details}
                for c in result.conditions
            ],
            "summary": result.summary,
        }

        new_status = "qualified" if result.qualified else "failed"
        self.repo.update_evaluation(
            record.id,
            status=new_status,
            tracking_days_done=cfg.track_days,
            day_data_json=json.dumps(day_data, ensure_ascii=False),
            cond_price_hold=result.conditions[0].passed if len(result.conditions) > 0 else None,
            cond_new_highs=result.conditions[1].passed if len(result.conditions) > 1 else None,
            cond_volume=result.conditions[2].passed if len(result.conditions) > 2 else None,
            conditions_met=result.conditions_met,
            score=float(result.score),
            score_details_json=json.dumps(score_details, ensure_ascii=False),
        )
        return result

    # ------------------------------------------------------------------
    # 报告与通知
    # ------------------------------------------------------------------

    def _send_report(self, scan_date: date, stats: Dict[str, Any]) -> bool:
        qualified = self.repo.get_qualified_records(target_date=scan_date)
        tracking = self.repo.get_recent_records(days=7, limit=50)
        tracking_active = [r for r in tracking if r.status == "detected"]

        if not qualified and not tracking_active:
            logger.info("无入围股和跟踪中股票，跳过通知")
            return False

        content = self._build_markdown(scan_date, stats, qualified, tracking_active)
        try:
            from src.notification import NotificationService
            notifier = NotificationService()
            ok = notifier.send(content, route_type="alert", email_send_to_all=True)
            if ok:
                self.repo.mark_notified([r.id for r in qualified])
            return ok
        except Exception as e:
            logger.warning("通知发送失败: %s", e)
            return False

    def _build_markdown(self, scan_date, stats, qualified, tracking_active) -> str:
        lines = [
            f"# 涨停余温扫描 ({scan_date.isoformat()})",
            "",
            f"> 检测到 {stats.get('detected', 0)} 只新涨停 | "
            f"评估 {stats.get('evaluated', 0)} 只 | "
            f"入围 {stats.get('qualified', 0)} 只 | "
            f"淘汰 {stats.get('failed', 0)} 只",
            "",
        ]

        if qualified:
            lines.append(f"## 🔥 明日关注(余温合格 {len(qualified)} 只)")
            lines.append("")
            lines.append("> 涨停后跟踪期满、余温特征成立,可尝试**次日低吸**;止损纪律严格执行。")
            lines.append("")
            for idx, r in enumerate(qualified, 1):
                # 解析跟踪期日线,取最新收盘
                latest_close = r.limit_up_price
                try:
                    dd = json.loads(r.day_data_json) if r.day_data_json else []
                    if dd:
                        latest_close = float(dd[-1].get("close", r.limit_up_price))
                except Exception:
                    dd = []
                pullback = ((latest_close - r.limit_up_price) / r.limit_up_price * 100) if r.limit_up_price else 0
                # 买入建议:按回踩程度分类(回踩低吸 vs 已启动回踩关注)
                if pullback <= 2.0:
                    # 仍在涨停价附近(回踩/横盘):低吸涨停价带
                    buy_low = r.limit_up_price * 0.95
                    buy_high = r.limit_up_price * 1.00
                    stop = r.limit_up_price * 0.93
                    action = "回踩低吸"
                else:
                    # 已离开涨停价向上:回调到最新价附近关注,不追高
                    buy_low = latest_close * 0.97
                    buy_high = latest_close * 1.00
                    stop = latest_close * 0.93
                    action = "回踩关注(已启动,勿追高)"
                # 满足条件列表
                met_names = []
                if r.cond_price_hold:
                    met_names.append("价格守住")
                if r.cond_new_highs:
                    met_names.append("新高")
                if r.cond_volume:
                    met_names.append("量能")
                met_str = "、".join(met_names) if met_names else "无"
                cb = r.consecutive_boards or 1
                lines.append(
                    f"**{idx}. {r.name or r.code}({r.code})** {r.industry or ''} | "
                    f"评分 {r.score:.0f} | {cb}连板"
                )
                lines.append(
                    f"- 涨停价 {r.limit_up_price:.2f} → 最新 {latest_close:.2f}"
                    f"(回踩 {pullback:+.1f}%)"
                )
                lines.append(f"- ✅ 满足 {r.conditions_met or 0}/3:{met_str}")
                lines.append(
                    f"- 🎯 {action} **{buy_low:.2f}-{buy_high:.2f}** | "
                    f"🛑 止损 **{stop:.2f}**"
                )
                lines.append("")

        if tracking_active:
            lines.append("## 跟踪中")
            lines.append("")
            lines.append("| 代码 | 名称 | 涨停日期 | 涨停价 | 连板 | 行业 |")
            lines.append("| ---- | ---- | -------- | ------: | ---: | ---- |")
            for r in tracking_active[:20]:
                cb = r.consecutive_boards or 1
                lines.append(
                    f"| {r.code} | {r.name or '-'} | {r.limit_up_date} | "
                    f"{r.limit_up_price:.2f} | {cb} | {r.industry or '-'} |"
                )
            lines.append("")

        lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        return "\n".join(lines)
