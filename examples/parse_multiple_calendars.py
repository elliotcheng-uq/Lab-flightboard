#!/usr/bin/env python3
"""Parse multiple equipment calendars from a JSON config file.

Usage:
    python examples/parse_multiple_calendars.py <config.json>

Example:
    python examples/parse_multiple_calendars.py examples/equipment_config.json
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lab_flightboard import (
    load_equipment_config,
    enabled_equipment,
    parse_all_equipment,
    EquipmentConfigError,
)


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    config_path = sys.argv[1]

    try:
        all_equipment = load_equipment_config(config_path)
    except EquipmentConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    active = enabled_equipment(all_equipment)
    print(f"Loaded {len(all_equipment)} equipment entries ({len(active)} enabled).\n")

    bookings, errors = parse_all_equipment(active)

    if errors:
        print("Errors encountered:")
        for err in errors:
            print(f"  [{err['equipment_id']}] {err['error']}")
        print()

    if not bookings:
        print("No bookings found.")
        return

    print(f"Found {len(bookings)} total booking(s):\n")
    current_eq = None
    for b in bookings:
        if b.equipment_id != current_eq:
            current_eq = b.equipment_id
            print(f"--- {b.equipment_name} ---")
        status_tag = f"[{b.status}]" if b.status else ""
        print(f"  {b.start.isoformat()}  {b.title}  {status_tag}")
        if b.end:
            print(f"    Ends: {b.end.isoformat()}")
        print()


if __name__ == "__main__":
    main()
