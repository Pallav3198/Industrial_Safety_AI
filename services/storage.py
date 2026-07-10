"""
services/storage.py
---------------------
A small JSON-file-backed persistence layer.

This is intentionally NOT a real database. For a hackathon prototype, a
flat JSON file is enough to demonstrate the full Add Facility wizard
without adding SQL/ORM setup overhead.

To swap in a real database later: keep these exact function signatures
and reimplement their bodies -- routes/*.py never touch the JSON file
directly, so nothing else needs to change.
"""

import json
import os
import threading
from typing import Optional, List

from config import Config
from models.factory import Factory
from models.monitored_parameter import MonitoredParameter
from models.person import Person
from models.checklist_record import ChecklistRecord
from models.permit_record import PermitRecord

# Guards the JSON file against corruption from concurrent requests.
# Fine for a single-process dev server; replace with real DB transactions
# before running this under multiple worker processes.
_lock = threading.Lock()


def _ensure_data_file():
    os.makedirs(Config.DATA_FOLDER, exist_ok=True)
    if not os.path.exists(Config.FACTORIES_FILE):
        with open(Config.FACTORIES_FILE, "w") as f:
            json.dump({}, f)


def _read_all() -> dict:
    _ensure_data_file()
    with open(Config.FACTORIES_FILE, "r") as f:
        return json.load(f)


def _write_all(data: dict):
    with open(Config.FACTORIES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_factory(factory: Factory) -> None:
    """Insert a new factory record, or overwrite an existing one with the
    same id."""
    with _lock:
        data = _read_all()
        data[factory.id] = factory.to_dict()
        _write_all(data)


def get_factory(factory_id: str) -> Optional[Factory]:
    with _lock:
        data = _read_all()
        record = data.get(factory_id)
        return Factory.from_dict(record) if record else None


def list_factories() -> List[Factory]:
    with _lock:
        data = _read_all()
        return [Factory.from_dict(r) for r in data.values()]


# ---------------------------------------------------------------------------
# MonitoredParameter CRUD (was "Sensor CRUD" -- see models/monitored_parameter.py)
# ---------------------------------------------------------------------------

def delete_monitored_parameter(factory_id: str, parameter_id: str) -> bool:
    """Returns True if a parameter was actually removed, False if the
    factory or parameter didn't exist."""
    factory = get_factory(factory_id)
    if not factory:
        return False
    before = len(factory.monitored_parameters)
    factory.monitored_parameters = [p for p in factory.monitored_parameters if p.id != parameter_id]
    save_factory(factory)
    return len(factory.monitored_parameters) < before


def upsert_monitored_parameter(factory_id: str, parameter: MonitoredParameter) -> bool:
    """Add a new parameter, or update an existing one if its id already
    exists on this factory. Returns False only if the factory itself
    doesn't exist."""
    factory = get_factory(factory_id)
    if not factory:
        return False
    for i, p in enumerate(factory.monitored_parameters):
        if p.id == parameter.id:
            factory.monitored_parameters[i] = parameter
            save_factory(factory)
            return True
    factory.monitored_parameters.append(parameter)
    save_factory(factory)
    return True


def get_monitored_parameter(factory_id: str, parameter_id: str) -> Optional[MonitoredParameter]:
    factory = get_factory(factory_id)
    if not factory:
        return None
    return next((p for p in factory.monitored_parameters if p.id == parameter_id), None)


# ---------------------------------------------------------------------------
# Person CRUD (was "Employee CRUD" -- see models/person.py). Mirrors the
# MonitoredParameter CRUD functions exactly, same pattern.
# ---------------------------------------------------------------------------

def delete_person(factory_id: str, person_id: str) -> bool:
    factory = get_factory(factory_id)
    if not factory:
        return False
    before = len(factory.people)
    factory.people = [p for p in factory.people if p.id != person_id]
    save_factory(factory)
    return len(factory.people) < before


def upsert_person(factory_id: str, person: Person) -> bool:
    factory = get_factory(factory_id)
    if not factory:
        return False
    for i, p in enumerate(factory.people):
        if p.id == person.id:
            factory.people[i] = person
            save_factory(factory)
            return True
    factory.people.append(person)
    save_factory(factory)
    return True


def get_person(factory_id: str, person_id: str) -> Optional[Person]:
    factory = get_factory(factory_id)
    if not factory:
        return None
    return next((p for p in factory.people if p.id == person_id), None)


# ---------------------------------------------------------------------------
# ChecklistRecord CRUD (PSSR + MOC -- see models/checklist_record.py)
# ---------------------------------------------------------------------------

def delete_checklist_record(factory_id: str, record_id: str) -> bool:
    factory = get_factory(factory_id)
    if not factory:
        return False
    before = len(factory.checklist_records)
    factory.checklist_records = [c for c in factory.checklist_records if c.id != record_id]
    save_factory(factory)
    return len(factory.checklist_records) < before


def upsert_checklist_record(factory_id: str, record: ChecklistRecord) -> bool:
    factory = get_factory(factory_id)
    if not factory:
        return False
    for i, c in enumerate(factory.checklist_records):
        if c.id == record.id:
            factory.checklist_records[i] = record
            save_factory(factory)
            return True
    factory.checklist_records.append(record)
    save_factory(factory)
    return True


def get_checklist_record(factory_id: str, record_id: str) -> Optional[ChecklistRecord]:
    factory = get_factory(factory_id)
    if not factory:
        return None
    return next((c for c in factory.checklist_records if c.id == record_id), None)


# ---------------------------------------------------------------------------
# PermitRecord CRUD (see models/permit_record.py)
# ---------------------------------------------------------------------------

def delete_permit_record(factory_id: str, permit_id: str) -> bool:
    factory = get_factory(factory_id)
    if not factory:
        return False
    before = len(factory.permit_records)
    factory.permit_records = [p for p in factory.permit_records if p.id != permit_id]
    save_factory(factory)
    return len(factory.permit_records) < before


def upsert_permit_record(factory_id: str, permit: PermitRecord) -> bool:
    factory = get_factory(factory_id)
    if not factory:
        return False
    for i, p in enumerate(factory.permit_records):
        if p.id == permit.id:
            factory.permit_records[i] = permit
            save_factory(factory)
            return True
    factory.permit_records.append(permit)
    save_factory(factory)
    return True


def get_permit_record(factory_id: str, permit_id: str) -> Optional[PermitRecord]:
    factory = get_factory(factory_id)
    if not factory:
        return None
    return next((p for p in factory.permit_records if p.id == permit_id), None)


# ---------------------------------------------------------------------------
# Generic field updates -- used by any section that's a handful of scalar/
# list/dict fields directly on Factory, with no dedicated CRUD needed
# (e.g. negligence history, validation answers, attendance config, and
# the new Part A/B/C/E simple-record sections).
# ---------------------------------------------------------------------------

def update_factory_fields(factory_id: str, **fields) -> bool:
    """Update one or more top-level fields on a factory record directly,
    e.g. update_factory_fields(fid, negligence_history="...", validation_complete=True).
    Returns False if the factory doesn't exist or a field name is invalid."""
    factory = get_factory(factory_id)
    if not factory:
        return False
    for key, value in fields.items():
        if not hasattr(factory, key):
            return False
        setattr(factory, key, value)
    save_factory(factory)
    return True