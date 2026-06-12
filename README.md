# Lab Flightboard

Airport-style dashboard for lab equipment bookings, instrument status, and incident alerts.

## Install

```bash
pip install -e ".[dev]"
```

## Quick start

```bash
# Inspect a calendar feed
python examples/inspect_calendar.py "https://example.com/calendar.ics"

# Parse a single calendar
python examples/parse_single_calendar.py sem-01 "SEM 01" "https://example.com/sem.ics"

# Parse multiple calendars from a JSON config
python examples/parse_multiple_calendars.py examples/equipment_config.json
```

## Run tests

```bash
pytest
```

## Equipment config format

```json
[
  {
    "equipment_id": "sem-01",
    "equipment_name": "SEM 01",
    "calendar_url": "https://example.com/sem-01.ics",
    "display_order": 1
  }
]
```

## Privacy

Calendar URLs may contain private access tokens. The library never logs full URLs — only the scheme and host are shown in log output.
