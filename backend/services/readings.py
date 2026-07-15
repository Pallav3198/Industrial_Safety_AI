"""
services/readings.py
------------------------
Simplest possible provision for continuous sensor/system readings.
Deliberately not using Kafka or a time-series-specific database --
this is a plain SQLite table (models_db.Reading) with two functions:
write a reading, read recent readings. Revisit if/when real throughput
or true streaming semantics are actually needed.
"""

from datetime import datetime, timedelta

from db import SessionLocal
from models_db import Reading


def record_reading(factory_id: str, parameter_id: str, value: float = None, raw_value: str = None) -> Reading:
    """Writes one reading. Call this every time a new value comes in --
    for now that means your simulated feeder; later, whatever a real
    sensor integration calls when a new value arrives."""
    session = SessionLocal()
    reading = Reading(
        factory_id=factory_id,
        parameter_id=parameter_id,
        value=value,
        raw_value=raw_value,
        timestamp=datetime.utcnow(),
    )
    session.add(reading)
    session.commit()
    return reading


def get_recent_readings(factory_id: str, parameter_id: str = None, hours: int = 12):
    """Returns readings from the last `hours` hours (default 12, per
    the review-window requirement). Pass parameter_id to scope to one
    sensor; omit it to get every reading for the facility."""
    session = SessionLocal()
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    query = session.query(Reading).filter(
        Reading.factory_id == factory_id,
        Reading.timestamp >= cutoff,
    )
    if parameter_id:
        query = query.filter(Reading.parameter_id == parameter_id)
    return query.order_by(Reading.timestamp.asc()).all()