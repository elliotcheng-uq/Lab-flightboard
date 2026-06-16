#!/usr/bin/env python3
"""Inspect a calendar feed and print a diagnostic summary.

Useful for understanding what fields a booking system (e.g. PPMS) actually exports.
The full calendar URL is NOT printed to avoid leaking private access tokens.

Usage:
    python examples/inspect_calendar.py <ics_url>

Example:
    python examples/inspect_calendar.py "https://example.com/calendar.ics?token=secret"
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from lab_flightboard import fetch_ical_from_url, parse_ical_bytes, CalendarFetchError, CalendarParseError
from lab_flightboard.ical_parser import _to_datetime


def _safe_url(url: str) -> str:
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}/..."
    except Exception:
        return "<URL>"


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    print(f"Fetching calendar from: {_safe_url(url)}\n")

    try:
        data = fetch_ical_from_url(url)
        cal = parse_ical_bytes(data)
    except (CalendarFetchError, CalendarParseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Calendar-level metadata
    cal_name = str(cal.get("X-WR-CALNAME", "<unnamed>"))
    cal_tz = str(cal.get("X-WR-TIMEZONE", "<not set>"))
    print(f"Calendar name:     {cal_name}")
    print(f"Calendar timezone: {cal_tz}")
    print()

    # Collect VEVENT stats
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    print(f"VEVENT count:      {len(events)}")

    starts = []
    ends = []
    all_field_names: set[str] = set()
    x_fields: set[str] = set()
    has_rrule = False
    sample_event = None

    for ev in events:
        dtstart_raw = ev.get("DTSTART")
        dtend_raw = ev.get("DTEND")
        if dtstart_raw:
            dt = _to_datetime(dtstart_raw.dt)
            if dt:
                starts.append(dt)
        if dtend_raw:
            dt = _to_datetime(dtend_raw.dt)
            if dt:
                ends.append(dt)
        for key in ev.keys():
            k = str(key)
            all_field_names.add(k)
            if k.upper().startswith("X-"):
                x_fields.add(k)
        if ev.get("RRULE") is not None:
            has_rrule = True
        if sample_event is None:
            sample_event = ev

    if starts:
        print(f"Earliest event:    {min(starts).isoformat()}")
        print(f"Latest event:      {max(starts).isoformat()}")
    else:
        print("Earliest event:    —")
        print("Latest event:      —")

    print(f"Recurring events:  {'yes' if has_rrule else 'no'}")
    print()

    standard_fields = sorted(f for f in all_field_names if not f.upper().startswith("X-"))
    print(f"Standard iCal fields detected ({len(standard_fields)}):")
    for f in standard_fields:
        print(f"  {f}")
    print()

    if x_fields:
        print(f"Custom X-* fields detected ({len(x_fields)}):")
        for f in sorted(x_fields):
            print(f"  {f}")
    else:
        print("No custom X-* fields detected.")
    print()

    if sample_event is not None:
        print("Sample event fields:")
        for key, val in sample_event.items():
            print(f"  {key}: {str(val)[:120]}")


if __name__ == "__main__":
    main()
