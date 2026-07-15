"""
db.py
--------
SQLAlchemy engine/session setup for the monitoring database (live
readings, rule evaluation history, and flags). This is deliberately
separate from services/storage.py -- that module owns the existing
Factory JSON data (facilities, sensors, people, permits, etc.) and is
untouched by this. Every row in this database references a factory_id
(and, where relevant, a rule_id) but the actual Factory/Rule records
still live in the JSON file.

Using SQLite for now (single file, zero setup). Swapping to Postgres
later is a one-line change to DATABASE_URL below -- nothing else in
the codebase needs to change, since all access goes through the
SQLAlchemy session this module provides.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from config import Config

DATABASE_URL = "sqlite:///" + os.path.join(Config.DATA_FOLDER, "monitoring.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))


def init_db():
    """Creates all tables defined in models_db.py if they don't already
    exist. Safe to call on every app startup -- no-op if tables are
    already present."""
    import models_db  # noqa: F401 -- imported for its side effect of registering tables on Base.metadata
    models_db.Base.metadata.create_all(bind=engine)