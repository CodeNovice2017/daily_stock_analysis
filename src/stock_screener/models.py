# -*- coding: utf-8 -*-
"""涨停余温扫描器 ORM 模型 — 自建独立表，不修改上游 storage.py。

复用上游 DatabaseManager 的引擎和 create_all 机制，
但模型定义在本模块内，减少 merge 冲突。
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    desc,
    func,
    select,
)

logger = logging.getLogger(__name__)


def _get_base():
    """延迟获取上游 Base，避免循环导入。"""
    from src.storage import Base
    return Base


def _get_db():
    """延迟获取上游 DatabaseManager 单例。"""
    from src.storage import DatabaseManager
    return DatabaseManager.get_instance()


# ---------------------------------------------------------------------------
# ORM 模型（延迟注册到上游 Base.metadata）
# ---------------------------------------------------------------------------

_CLASS = None


def _ensure_model():
    global _CLASS
    if _CLASS is not None:
        return _CLASS

    Base = _get_base()

    class LimitUpRecord(Base):
        """涨停余温跟踪记录。"""

        __tablename__ = "limit_up_records"

        id = Column(Integer, primary_key=True, autoincrement=True)
        code = Column(String(10), nullable=False, index=True)
        name = Column(String(50))
        status = Column(String(16), nullable=False, default="detected", index=True)

        limit_up_date = Column(Date, nullable=False, index=True)
        limit_up_price = Column(Float, nullable=False)
        limit_up_high = Column(Float)
        limit_up_volume = Column(Float)
        limit_up_pct = Column(Float)
        limit_up_amount = Column(Float)
        consecutive_boards = Column(Integer, default=1)
        industry = Column(String(32))
        seal_amount = Column(Float)
        break_count = Column(Integer, default=0)
        first_limit_time = Column(String(10))

        tracking_days_done = Column(Integer, nullable=False, default=0)
        day_data_json = Column(Text)

        cond_price_hold = Column(Boolean)
        cond_new_highs = Column(Boolean)
        cond_volume = Column(Boolean)
        conditions_met = Column(Integer)
        score = Column(Float, default=0)
        score_details_json = Column(Text)

        created_at = Column(DateTime, default=datetime.now)
        updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
        notified_at = Column(DateTime)

        __table_args__ = (
            UniqueConstraint("code", "limit_up_date", name="uix_limit_up_code_date"),
            Index("ix_limit_up_status_date", "status", "limit_up_date"),
        )

    _CLASS = LimitUpRecord
    return LimitUpRecord


def get_model():
    return _ensure_model()


def ensure_table():
    """确保表已创建（通过 session 的公共 bind，不访问私有 _engine）。"""
    model = _ensure_model()
    db = _get_db()
    with db.get_session() as session:
        model.__table__.create(bind=session.bind, checkfirst=True)
        session.commit()


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class LimitUpRepository:
    """涨停余温记录的数据库访问。"""

    def __init__(self):
        self.db = _get_db()
        ensure_table()

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
    ):
        Record = get_model()
        with self.db.get_session() as session:
            existing = session.execute(
                select(Record).where(
                    and_(Record.code == code, Record.limit_up_date == limit_up_date)
                )
            ).scalar_one_or_none()

            if existing:
                existing.updated_at = datetime.now()
                if name:
                    existing.name = name
                session.commit()
                session.refresh(existing)
                return existing

            record = Record(
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
        lookback_days: int = 60,
    ) -> list:
        """返回 detected 状态的跟踪记录。

        仅做粗粒度时间过滤（避免扫描远古垃圾），交易日可评估性由 service 层
        用 holiday 模块精确判断。
        """
        Record = get_model()
        ref = reference_date or date.today()
        cutoff = ref - timedelta(days=lookback_days)
        with self.db.get_session() as session:
            rows = session.execute(
                select(Record)
                .where(
                    and_(Record.status == "detected", Record.limit_up_date >= cutoff)
                )
                .order_by(Record.limit_up_date)
            ).scalars().all()
            return list(rows)

    def get_qualified_records(
        self,
        target_date: Optional[date] = None,
        limit: int = 50,
    ) -> list:
        Record = get_model()
        with self.db.get_session() as session:
            q = (
                select(Record)
                .where(Record.status == "qualified")
                .order_by(desc(Record.score))
            )
            if target_date:
                dt = datetime.combine(target_date, datetime.min.time())
                q = q.where(Record.updated_at >= dt)
            return list(session.execute(q.limit(limit)).scalars().all())

    def get_recent_records(self, days: int = 7, limit: int = 100) -> list:
        Record = get_model()
        cutoff = date.today() - timedelta(days=days)
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(Record)
                    .where(Record.limit_up_date >= cutoff)
                    .order_by(desc(Record.limit_up_date))
                    .limit(limit)
                ).scalars().all()
            )

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
        Record = get_model()
        with self.db.get_session() as session:
            record = session.get(Record, record_id)
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

    def mark_notified(self, record_ids: list) -> int:
        Record = get_model()
        count = 0
        with self.db.get_session() as session:
            for rid in record_ids:
                record = session.get(Record, rid)
                if record:
                    record.notified_at = datetime.now()
                    count += 1
            session.commit()
        return count

    def expire_stale_records(self, max_age_days: int = 10) -> int:
        Record = get_model()
        cutoff = date.today() - timedelta(days=max_age_days)
        with self.db.get_session() as session:
            rows = session.execute(
                select(Record).where(
                    and_(Record.status == "detected", Record.limit_up_date < cutoff)
                )
            ).scalars().all()
            for record in rows:
                record.status = "expired"
                record.updated_at = datetime.now()
            session.commit()
            return len(rows)

    def count_by_status(self) -> Dict[str, int]:
        Record = get_model()
        with self.db.get_session() as session:
            rows = session.execute(
                select(Record.status, func.count(Record.id)).group_by(Record.status)
            ).all()
            return dict(rows)
