# iCal Field Extraction Reference

This document describes how Lab Flightboard extracts booking data from iCalendar (`.ics`) feeds, covering instrument and room identification, date and time handling, user details, and how the parser detects interruptions and status changes.

---

## Overview

Each `VEVENT` component in an iCal feed is converted into a `CalendarBooking` object. The parser reads standard RFC 5545 fields where present, calculates derived values (e.g. end time from duration), and preserves any vendor-specific `X-*` fields for later inspection or custom mapping.

Fields that are missing are silently set to `None` — the parser never crashes on an incomplete event.

---

## 1. Instrument and Room Identification

### Standard fields

| iCal field | `CalendarBooking` attribute | Notes |
|---|---|---|
| `LOCATION` | `location` | Free-text room or building name |
| `SUMMARY` | `title` | Often contains the instrument or booking type name |
| `CATEGORIES` | `categories` | Comma-separated list; e.g. `Training,SEM` |

**Example ICS:**
```
SUMMARY:SEM Training Session
LOCATION:Electron Microscopy Lab
CATEGORIES:Training,SEM
```

**Resulting object:**
```python
booking.title      # "SEM Training Session"
booking.location   # "Electron Microscopy Lab"
booking.categories # ["Training", "SEM"]
```

### Equipment identity from the parser config

The `equipment_id` and `equipment_name` fields are **not** read from the iCal feed — they come from the equipment configuration file (JSON) that maps each calendar URL to a human-readable name. This means the same ICS feed always produces consistent equipment identifiers regardless of what the vendor puts in the feed.

```python
booking.equipment_id   # "sem-01"    (from config)
booking.equipment_name # "SEM 01"    (from config)
```

See [`equipment_config.py`](../lab_flightboard/equipment_config.py) and the [example config](../examples/equipment_config.json).

### Vendor-specific instrument fields (`X-*`)

Facility management systems often export their internal instrument ID as a custom field. These are preserved in `vendor_fields` (a dict of only `X-*` keys) and also in `raw_properties` (everything).

**Common patterns seen in practice:**

| Vendor field | Description |
|---|---|
| `X-PPMS-EQUIPMENT-ID` | Internal instrument ID in PPMS |
| `X-PPMS-BOOKING-ID` | Booking reference number |
| `X-WR-CALNAME` | Calendar-level name (on the `VCALENDAR`, not per event) |

```python
booking.vendor_fields
# {"X-PPMS-EQUIPMENT-ID": "SEM-01", "X-PPMS-BOOKING-ID": "12345"}
```

If you need to map a vendor instrument ID back to your own `equipment_id`, do it in post-processing using `vendor_fields`:

```python
ppms_id = booking.vendor_fields.get("X-PPMS-EQUIPMENT-ID")
```

---

## 2. Date and Time Extraction

### Start time (`DTSTART`)

`DTSTART` is the only required field. If it is absent the event is skipped with a warning log entry.

The parser handles three variants:

| DTSTART format | Example | Result |
|---|---|---|
| UTC datetime | `DTSTART:20260615T090000Z` | `datetime` with `tzinfo=UTC` |
| Timezone-aware | `DTSTART;TZID=Australia/Brisbane:20260615T090000` | `datetime` with named tz |
| All-day date | `DTSTART;VALUE=DATE:20260615` | `datetime` at midnight UTC |

```python
booking.start  # datetime(2026, 6, 15, 9, 0, tzinfo=<Brisbane tz>)
```

### End time (`DTEND` / `DURATION`)

The parser resolves the end time in this order:

1. **`DTEND`** — used directly if present.
2. **`DURATION`** — added to `DTSTART` to calculate the end time.
3. **Neither** — `booking.end` is `None`. The booking has an unknown duration.

```python
# DTEND present:
booking.end            # datetime(2026, 6, 15, 11, 0, ...)
booking.duration_minutes  # 120.0

# DURATION:PT2H present, no DTEND:
booking.end            # start + timedelta(hours=2)
booking.duration_minutes  # 120.0

# Neither:
booking.end            # None
booking.duration_minutes  # None
```

### Timezone handling

- Timezone-aware datetimes are preserved as-is with their `tzinfo` intact.
- All-day `DATE` values are converted to `datetime` at **midnight UTC**.
- The `is_current(now)` helper normalises naive datetimes to UTC before comparison, so mixing aware and naive values is safe.

### Recurring events

`DTSTART` in a recurring event is the **first** occurrence. There are two parsing modes:

| Mode | Function | What you get |
|---|---|---|
| Non-expanded | `parse_events_from_calendar` | One `CalendarBooking` per `VEVENT` (the template). `is_recurring=True`. |
| Expanded | `parse_occurrences_from_url` | One `CalendarBooking` per occurrence within the requested window. |

**Relevant iCal fields:**

| Field | `CalendarBooking` attribute | Notes |
|---|---|---|
| `RRULE` | `is_recurring = True` | Recurrence rule (e.g. `FREQ=WEEKLY;COUNT=3`) |
| `EXDATE` | — (preserved in `raw_properties`) | Dates excluded from the recurrence |
| `RECURRENCE-ID` | `is_recurring = True` | Marks an exception/override for one occurrence |
| `SEQUENCE` | `sequence` | Increments each time an event is modified |

```python
# Expand recurrences within a window:
from datetime import datetime, timezone
from lab_flightboard import parse_occurrences_from_url

bookings = parse_occurrences_from_url(
    url="https://example.com/calendar.ics",
    equipment_id="sem-01",
    equipment_name="SEM 01",
    start=datetime(2026, 6, 1, tzinfo=timezone.utc),
    end=datetime(2026, 6, 30, tzinfo=timezone.utc),
)
# Returns one CalendarBooking per occurrence in June
```

### Modification timestamps

| iCal field | `CalendarBooking` attribute | Notes |
|---|---|---|
| `CREATED` | `created` | When the booking was first made |
| `LAST-MODIFIED` | `last_modified` | When it was last changed |
| `DTSTAMP` | — (in `raw_properties`) | When the iCal record was generated |

---

## 3. User Details

### Organiser

`ORGANIZER` typically identifies the person who made the booking (the account holder). The parser strips the `mailto:` prefix automatically.

| iCal field | `CalendarBooking` attribute | Raw example | Parsed value |
|---|---|---|---|
| `ORGANIZER` | `organiser` | `mailto:jsmith@example.edu` | `jsmith@example.edu` |

```python
booking.organiser  # "jsmith@example.edu"
```

### Attendees

`ATTENDEE` is preserved in `raw_properties` but not yet mapped to a dedicated attribute. To read it:

```python
attendee = booking.raw_properties.get("ATTENDEE")
# "mailto:labstaff@example.edu"
```

### Description field

Many booking systems embed structured user information (name, project, account code) in the free-text `DESCRIPTION` field. There is no universal format — each system has its own convention.

```python
booking.description
# "User: Jane Smith\nProject: Nano-2026\nAccount: RES-4421"
```

Parse it with a custom function based on what your system exports.

### Vendor-specific user fields (`X-*`)

Some systems export user identity as custom fields. Inspect `vendor_fields` after parsing to find them:

```python
booking.vendor_fields
# {
#   "X-SYSTEM-USER-ID":    "jsmith",
#   "X-SYSTEM-PROJECT":    "Nano-2026",
#   "X-SYSTEM-ACCOUNT":    "RES-4421",
# }
```

### Reserved model fields (populated if a custom extractor maps them)

The `CalendarBooking` model includes these fields as placeholders. They are not populated by the core parser because standard iCal has no canonical fields for them, but a post-processing step can fill them from `vendor_fields` or `description`:

```python
booking.user_name       # str | None
booking.user_email      # str | None
booking.project         # str | None
booking.account_code    # str | None
booking.booking_reference  # str | None
```

**Example post-processor:**

```python
def enrich_from_vendor_fields(booking: CalendarBooking) -> CalendarBooking:
    booking.user_email = booking.vendor_fields.get("X-SYSTEM-USER-EMAIL")
    booking.project    = booking.vendor_fields.get("X-SYSTEM-PROJECT")
    return booking
```

---

## 4. Interventions and Interruptions

This section covers how to detect bookings that are cancelled, modified, pending, or represent a maintenance window — important for a live dashboard display.

### Cancellations

| iCal field | `CalendarBooking` attribute | Value |
|---|---|---|
| `STATUS:CANCELLED` | `is_cancelled` | `True` |
| `STATUS:CONFIRMED` | `is_cancelled` | `False` |

```python
booking.is_cancelled  # True if STATUS == "CANCELLED"
booking.status        # "CANCELLED" (raw string, also preserved)
```

Cancelled events **are kept** in the parsed output so a dashboard can explicitly show "Booking cancelled" rather than silently removing the time slot.

### Tentative / unconfirmed bookings

```python
booking.status  # "TENTATIVE"
```

There is no dedicated boolean for tentative — check `booking.status` directly. Useful for showing "Pending confirmation" on a display.

### STATUS values

| `STATUS` value | Meaning in a booking context |
|---|---|
| `CONFIRMED` | Booking is confirmed and active |
| `TENTATIVE` | Booking is provisional, not yet confirmed |
| `CANCELLED` | Booking was cancelled; `is_cancelled = True` |

### TRANSP (transparency)

`TRANSP:TRANSPARENT` means the event does not mark the time as busy (e.g. an information-only entry). Preserved in `raw_properties`:

```python
booking.raw_properties.get("TRANSP")  # "TRANSPARENT" or "OPAQUE"
```

### Maintenance and special categories

Categorised bookings can be identified via `categories`:

```python
"Maintenance" in booking.categories   # True for maintenance windows
"Training"    in booking.categories   # True for training sessions
```

Since `CATEGORIES` is free-text, the exact values depend on the booking system's configuration. Inspect `cal.x_fields` with `examples/inspect_calendar.py` to see what your system exports.

### Recurring event modifications

When a single occurrence of a recurring booking is modified or cancelled, the booking system emits a `VEVENT` with a `RECURRENCE-ID` pointing to the specific occurrence.

| Field | Meaning |
|---|---|
| `RRULE` | Defines the repeating pattern |
| `EXDATE` | Dates that are excluded (cancelled) from the series |
| `RECURRENCE-ID` | This event is a modification of one specific occurrence |

In **non-expanded mode** (`parse_events_from_calendar`), these override events appear as separate `CalendarBooking` objects with `is_recurring = True`. Match them to the parent series via `uid`:

```python
# The original recurring template and its exception share the same UID
bookings_for_series = [b for b in bookings if b.uid == "booking-003@example.com"]
```

In **expanded mode** (`parse_occurrences_from_url`), the `recurring_ical_events` library applies `EXDATE` exclusions and `RECURRENCE-ID` overrides automatically — the returned list already reflects the correct state of each occurrence.

### Detecting current, upcoming, and past bookings

```python
from datetime import datetime, timezone

now = datetime.now(timezone.utc)

current  = [b for b in bookings if b.is_current(now)]
upcoming = [b for b in bookings if b.start > now and not b.is_cancelled]
past     = [b for b in bookings if b.end and b.end < now]
```

`is_current()` uses `[start, end)` semantics — the event is active from its start up to (but not including) its end time.

---

## 5. Raw Property Access

Every field the iCal parser encounters — including unknown or future fields — is available in two dicts:

| Attribute | Contents |
|---|---|
| `raw_properties` | All properties on the VEVENT, as `{field_name: str}` |
| `vendor_fields` | Only `X-*` fields, as `{field_name: str}` |

This makes the parser forward-compatible: if a booking system adds a new field, you can read it from `raw_properties` without changing the parser.

```python
booking.raw_properties.keys()
# dict_keys(['UID', 'DTSTAMP', 'DTSTART', 'DTEND', 'SUMMARY',
#            'LOCATION', 'STATUS', 'ORGANIZER', 'CATEGORIES',
#            'X-PPMS-BOOKING-ID', 'X-PPMS-EQUIPMENT-ID'])

booking.vendor_fields
# {'X-PPMS-BOOKING-ID': '12345', 'X-PPMS-EQUIPMENT-ID': 'SEM-01'}
```

---

## 6. Summary Table

| Category | iCal field | `CalendarBooking` attribute | Always present? |
|---|---|---|---|
| **Instrument** | — | `equipment_id` | Yes (from config) |
| **Instrument** | — | `equipment_name` | Yes (from config) |
| **Instrument** | `LOCATION` | `location` | No |
| **Instrument** | `SUMMARY` | `title` | Yes (falls back to "Untitled booking") |
| **Instrument** | `CATEGORIES` | `categories` | No (empty list if absent) |
| **Instrument** | `X-*` | `vendor_fields` | No |
| **Date/Time** | `DTSTART` | `start` | Yes (required — event skipped if missing) |
| **Date/Time** | `DTEND` / `DURATION` | `end` | No (`None` if absent) |
| **Date/Time** | `RRULE` | `is_recurring` | No |
| **Date/Time** | `CREATED` | `created` | No |
| **Date/Time** | `LAST-MODIFIED` | `last_modified` | No |
| **Date/Time** | `SEQUENCE` | `sequence` | No |
| **User** | `ORGANIZER` | `organiser` | No |
| **User** | `DESCRIPTION` | `description` | No |
| **User** | `X-*` (vendor) | `vendor_fields` | No |
| **User** | — | `user_name` | No (set by post-processor) |
| **User** | — | `user_email` | No (set by post-processor) |
| **User** | — | `project` | No (set by post-processor) |
| **User** | — | `account_code` | No (set by post-processor) |
| **Interruption** | `STATUS` | `status`, `is_cancelled` | No |
| **Interruption** | `TRANSP` | `raw_properties["TRANSP"]` | No |
| **Interruption** | `EXDATE` | `raw_properties["EXDATE"]` | No |
| **Interruption** | `RECURRENCE-ID` | `is_recurring` | No |

---

## 7. Inspecting an Unknown Feed

Use the inspector script to discover what fields your booking system actually exports before writing any custom mapping logic:

```bash
python examples/inspect_calendar.py "https://example.com/calendar.ics"
```

Or use the browser-based tester (upload the `.ics` file or paste the URL):

```bash
.\serve.bat
# open http://localhost:5050
```

The tester shows all standard and `X-*` fields detected across the feed, a sample event dump, and whether recurring events are present.
