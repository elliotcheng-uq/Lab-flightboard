#!/usr/bin/env python3
"""Parse a single calendar URL and print its bookings.

Usage:
    python examples/parse_single_calendar.py <equipment_id> <equipment_name> <ics_url>

Example:
    python examples/parse_single_calendar.py sem-01 "SEM 01" "https://example.com/sem-01.ics"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lab_flightboard import (
    fetch_ical_from_url,
    parse_ical_bytes,
    parse_events_from_calendar,
    CalendarFetchError,
    CalendarParseError,
)


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)

    equipment_id, equipment_name, url = sys.argv[1], sys.argv[2], sys.argv[3]

    try:
        data = fetch_ical_from_url(url)
        cal = parse_ical_bytes(data)
        bookings = parse_events_from_calendar(
            cal, equipment_id, equipment_name, source_calendar_url=url
        )
    except (CalendarFetchError, CalendarParseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not bookings:
        print("No bookings found.")
        return

    print(f"Found {len(bookings)} booking(s) for {equipment_name}:\n")
    for b in sorted(bookings, key=lambda x: x.start):
        status_tag = f"[{b.status}]" if b.status else ""
        print(f"  {b.start.isoformat()}  {b.title}  {status_tag}")
        if b.end:
            print(f"    End:         {b.end.isoformat()}  ({b.duration_minutes:.0f} min)")
        if b.location:
            print(f"    Location:    {b.location}")
        if b.organiser:
            print(f"    Organiser:   {b.organiser}")
        if b.categories:
            print(f"    Categories:  {', '.join(b.categories)}")
        if b.vendor_fields:
            for k, v in b.vendor_fields.items():
                print(f"    {k}: {v}")
        print()


if __name__ == "__main__":
    main()
