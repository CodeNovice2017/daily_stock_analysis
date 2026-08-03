# -*- coding: utf-8 -*-
"""涨停余温跟踪记录的数据访问层。"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, desc, func, select

from src.storage import DatabaseManager, LimitUpRecord

logger = logging.getLogger(__name__)


class LimitUpRepository:
    """涨停余温记录的数据库访问。"""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def upsert_record(
        self,
        code: str,
        limit_up_date: date,
        *,
        name: Optional[str] = None,
        limit_up_price: float = 0.0,
        limit_up_high: Optional[float] = None,
        limit_up_volume: Optional[float] = None,
        limit_up_pct: Optional[float] = None,
        limit_up_amount: Optional[float] = None,
        consecutive_boards: int = 1,
        industry: Optional[str] = None,
        seal_amount: Optional[float] = None,
        break_count: int = 0,
        first_limit_time: Optional[str] = None,
    ) -> LimitUpRecord:
        """插入或更新涨停记录。"""
        with self.db.get_session() as session:
            existing = session.execute(
                select(LimitUpRecord).where(
                    and_(
                        LimitUpRecord.code == code,
                        LimitUpRecord.limit_up_date == limit_up_date,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                existing.updated_at = datetime.now()
                if name:
                    existing.name = name
                if seal_amount is not None:
                    existing.seal_amount = seal_amount
                if break_count is not None:
                    existing.break_count = break_count
                session.commit()
                session.refresh(existing)
                return existing

            record = LimitUpRecord(
                code=code,
                name=name,
                status="detected",
                limit_up_date=limit_up_date,
                limit_up_price=limit_up_price,
                limit_up_high=limit_up_high,
                limit_up_volume=limit_up_volume,
                limit_up_pct=limit_up_pct,
                limit_up_amount=limit_up_amount,
                consecutive_boards=consecutive_boards,
                industry=industry,
                seal_amount=seal_amount,
                break_count=break_count,
                first_limit_time=first_limit_time,
                tracking_days_done=0,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def get_tracking_records(
        self,
        min_tracking_days: int = 3,
        reference_date: Optional[date] = None,
    ) -> List[LimitUpRecord]:
        """返回需要评估的跟踪中记录（状态为 detected 且已跟踪足够天数）。"""
        ref = reference_date or date.today()
        with self.db.get_session() as session:
            cutoff = ref - timedelta(days=min_tracking_days + 2)
            rows = session.execute(
                select(LimitUpRecord).where(
                    and_(
                        LimitUpRecord.status == "detected",
                        LimitUpRecord.limit_up_date <= cutoff,
                    )
                ).order_by(LimitUpRecord.limit_up_date)
            ).scalars().all()
            return list(rows)

    def get_qualified_records(
        self,
        target_date: Optional[date] = None,
        limit: int = 50,
    ) -> List[LimitUpRecord]:
        """返回已入围的记录。"""
        with self.db.get_session() as session:
            q = select(LimitUpRecord).where(
                LimitUpRecord.status == "qualified"
            ).order_by(desc(LimitUpRecord.score))
            if target_date:
                q = q.where(LimitUpRecord.updated_at >= datetime.combine(target_date, datetime.min.time()))
            rows = session.execute(q.limit(limit)).scalars().all()
            return list(rows)

    def get_recent_records(
        self,
        days: int = 7,
        limit: int = 100,
    ) -> List[LimitUpRecord]:
        """返回最近 N 天的所有记录。"""
        with self.db.get_session() as session:
            cutoff = date.today() - timedelta(days=days)
            rows = session.execute(
                select(LimitUpRecord).where(
                    LimitUpRecord.limit_up_date >= cutoff
                ).order_by(desc(LimitUpRecord.limit_up_date)).limit(limit)
            ).scalars().all()
            return list(rows)

    def update_evaluation(
        self,
        record_id: int,
        *,
        status: str,
        tracking_days_done: int,
        day_data_json: Optional[str] = None,
        cond_price_hold: Optional[bool] = None,
        cond_new_highs: Optional[bool] = None,
        cond_volume: Optional[bool] = None,
        conditions_met: Optional[int] = None,
        score: float = 0,
        score_details_json: Optional[str] = None,
    ) -> bool:
        """更新记录的评估结果。"""
        with self.db.get_session() as session:
            record = session.get(LimitUpRecord, record_id)
            if not record:
                return False

            record.status = status
            record.tracking_days_done = tracking_days_done
            record.updated_at = datetime.now()

            if day_data_json is not None:
                record.day_data_json = day_data_json
            if cond_price_hold is not None:
                record.cond_price_hold = cond_price_hold
            if cond_new_highs is not None:
                record.cond_new_highs = cond_new_highs
            if cond_volume is not None:
                record.cond_volume = cond_volume
            if conditions_met is not None:
                record.conditions_met = conditions_met
            record.score = score
            if score_details_json is not None:
                record.score_details_json = score_details_json

            session.commit()
            return True

    def mark_notified(self, record_ids: List[int]) -> int:
        """标记记录已通知。"""
        if not record_ids:
            return 0
        with self.db.get_session() as session:
            count = 0
            for rid in record_ids:
                record = session.get(LimitUpRecord, rid)
                if record:
                    record.notified_at = datetime.now()
                    count += 1
            session.commit()
            return count

    def expire_stale_records(self, max_age_days: int = 10) -> int:
        """将超时未完成的记录标记为 expired。"""
        cutoff = date.today() - timedelta(days=max_age_days)
        with self.db.get_session() as session:
            rows = session.execute(
                select(LimitUpRecord).where(
                    and_(
                        LimitUpRecord.status == "detected",
                        LimitUpRecord.limit_up_date < cutoff,
                    )
                )
            ).scalars().all()

            count = 0
            for record in rows:
                record.status = "expired"
                record.updated_at = datetime.now()
                count += 1
            session.commit()
            return count

    def count_by_status(self) -> Dict[str, int]:
        """按状态统计记录数。"""
        with self.db.get_session() as session:
            rows = session.execute(
                select(LimitUpRecord.status, func.count(LimitUpRecord.id))
                .group_by(LimitUpRecord.status)
            ).all()
            return dict(rows)
