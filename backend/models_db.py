"""
models_db.py
---------------
SQLAlchemy ORM models for the monitoring database (see db.py). These
are separate from models/*.py, which are plain dataclasses for the
JSON-file-backed Factory/Rule/Person/etc. records. Everything here is
new, additive storage -- readings, evaluation history, and flags --
keyed by factory_id (and rule_id where relevant) back to those
existing JSON records.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Boolean, DateTime, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _new_id():
    return uuid.uuid4().hex[:12]


class Reading(Base):
    """One data point for a monitored parameter (sensor, attendance %,
    headcount, etc.) at a point in time. Populated starting in Step 4
    (live-value ingestion)."""
    __tablename__ = "readings"

    id = Column(String, primary_key=True, default=_new_id)
    factory_id = Column(String, nullable=False, index=True)
    parameter_id = Column(String, nullable=False, index=True)   # MonitoredParameter.id this reading belongs to
    value = Column(Float, nullable=True)
    raw_value = Column(String, nullable=True)   # original string, in case a reading isn't cleanly numeric
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class EvaluationRecord(Base):
    """Audit trail: one row per time a Rule's condition_tree was
    checked against data, whether or not it triggered. Populated
    starting in Step 5 (the Rule Evaluator)."""
    __tablename__ = "evaluation_records"

    id = Column(String, primary_key=True, default=_new_id)
    factory_id = Column(String, nullable=False, index=True)
    rule_id = Column(String, nullable=False, index=True)
    triggered = Column(Boolean, default=False)
    matched_condition_ids = Column(JSON, default=list)   # list of Condition.id values that evaluated true
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class Flag(Base):
    """A detected issue worth surfacing -- either a rule match (Tier 1,
    Step 5) or a statistical anomaly (Tier 2, Step 6)."""
    __tablename__ = "flags"

    id = Column(String, primary_key=True, default=_new_id)
    factory_id = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)       # "rule" | "anomaly"
    source_id = Column(String, nullable=True)      # rule_id if source == "rule"
    severity = Column(String, nullable=True)
    description = Column(String, nullable=True)
    resolved = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)