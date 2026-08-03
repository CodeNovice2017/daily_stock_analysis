from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from src.intraday.types import SignalLevel, SignalResult

logger = logging.getLogger(__name__)

Base = declarative_base()


class IntradaySignalRecord(Base):
    __tablename__ = "intraday_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    triggered_at = Column(DateTime, nullable=False)
    ts_code = Column(String(16), nullable=False, index=True)
    signal_name = Column(String(64), nullable=False)
    level = Column(String(16), nullable=False)
    price = Column(Float, nullable=False)
    data = Column(Text, nullable=True)


class IntradaySignalStore:
    def __init__(self, db_url: str = "") -> None:
        if not db_url:
            from src.config import get_config
            config = get_config()
            db_url = config.get_db_url()
        self._engine = create_engine(db_url, pool_pre_ping=True)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    def save(self, result: SignalResult) -> None:
        trade_date = result.triggered_at.date()
        record = IntradaySignalRecord(
            trade_date=trade_date,
            triggered_at=result.triggered_at,
            ts_code=result.ts_code,
            signal_name=result.signal_name,
            level=result.level.name,
            price=result.price,
            data=json.dumps(result.data) if result.data else None,
        )
        session = self._Session()
        try:
            session.add(record)
            session.commit()
            logger.info("Saved signal: %s on %s at %.2f", result.signal_name, result.ts_code, result.price)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def query_by_date(self, trade_date: date, ts_code: Optional[str] = None) -> List[Dict[str, Any]]:
        session = self._Session()
        try:
            q = session.query(IntradaySignalRecord).filter(IntradaySignalRecord.trade_date == trade_date)
            if ts_code:
                q = q.filter(IntradaySignalRecord.ts_code == ts_code)
            rows = q.order_by(IntradaySignalRecord.triggered_at).all()
            return [self._row_to_dict(r) for r in rows]
        finally:
            session.close()

    def has_fired_today(self, ts_code: str, signal_name: str, trade_date: date) -> bool:
        session = self._Session()
        try:
            return session.query(IntradaySignalRecord).filter(
                IntradaySignalRecord.ts_code == ts_code,
                IntradaySignalRecord.signal_name == signal_name,
                IntradaySignalRecord.trade_date == trade_date,
            ).first() is not None
        finally:
            session.close()

    def get_daily_stats(self, trade_date: date) -> Dict[str, Any]:
        records = self.query_by_date(trade_date)
        by_signal: Dict[str, int] = {}
        by_ts_code: Dict[str, int] = {}
        for r in records:
            by_signal[r["signal_name"]] = by_signal.get(r["signal_name"], 0) + 1
            by_ts_code[r["ts_code"]] = by_ts_code.get(r["ts_code"], 0) + 1
        return {
            "trade_date": str(trade_date),
            "total_signals": len(records),
            "by_signal": by_signal,
            "by_ts_code": by_ts_code,
        }

    @staticmethod
    def _row_to_dict(row: IntradaySignalRecord) -> Dict[str, Any]:
        return {
            "id": row.id,
            "trade_date": str(row.trade_date),
            "triggered_at": str(row.triggered_at),
            "ts_code": row.ts_code,
            "signal_name": row.signal_name,
            "level": row.level,
            "price": row.price,
            "data": json.loads(row.data) if row.data else {},
        }
