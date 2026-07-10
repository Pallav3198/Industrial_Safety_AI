"""
scripts/migrate_sensor_to_monitored_parameter.py
----------------------------------------------------
One-time migration for data/factories.json: renames the top-level
"sensors" key to "monitored_parameters" and "employees" to "people" on
every existing factory record, to match the Step 0 model rename
(models/sensor.py -> models/monitored_parameter.py,
models/employee.py -> models/person.py).

Field-level defaults (parameter_category, person_category, and all the
other new fields) are handled automatically by the dataclasses'
defaults the moment the data is loaded through Factory.from_dict() --
this script only needs to fix the two renamed top-level keys, since
dict.get("monitored_parameters", []) on old data would otherwise
silently return an empty list instead of the old "sensors" content.

Safe to run multiple times -- it's a no-op on records that have already
been migrated (already have the new keys and not the old ones).

Run with:
    python scripts/migrate_sensor_to_monitored_parameter.py
"""

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


def migrate():
    if not os.path.exists(Config.FACTORIES_FILE):
        print(f"No data file found at {Config.FACTORIES_FILE} -- nothing to migrate.")
        return

    backup_path = Config.FACTORIES_FILE + ".pre-migration-backup"
    shutil.copy2(Config.FACTORIES_FILE, backup_path)
    print(f"Backed up existing data to {backup_path}")

    with open(Config.FACTORIES_FILE, "r") as f:
        data = json.load(f)

    migrated_count = 0
    for factory_id, record in data.items():
        changed = False
        if "sensors" in record and "monitored_parameters" not in record:
            record["monitored_parameters"] = record.pop("sensors")
            changed = True
        if "employees" in record and "people" not in record:
            record["people"] = record.pop("employees")
            changed = True
        # New list/dict fields default fine via Factory's own dataclass
        # defaults on next load -- no need to backfill them here.
        if changed:
            migrated_count += 1

    with open(Config.FACTORIES_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Migrated {migrated_count} of {len(data)} factory record(s).")
    print("Done. If anything looks wrong, restore from the .pre-migration-backup file.")


if __name__ == "__main__":
    migrate()