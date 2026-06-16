# Config Reference

Every field of `billboard_config.json` in one place. The easiest way to produce
this file is the browser form at `http://localhost:5200/config` (or open
`examples/config_builder.html`). This page is the reference for editing it by
hand or understanding what the form writes.

> `billboard_config.json` is **git-ignored** because it may contain private feed
> URLs. Commit `examples/billboard_config.example.json` (placeholders) instead.

---

## Minimal config

Only `instruments` (each with an `equipment_name`) is really needed — everything
else has a sensible default. The smallest useful file:

```json
{
  "title": "My Lab",
  "timezone": "Australia/Brisbane",
  "instruments": [
    { "equipment_name": "SEM 01", "room": "Room 101", "calendar_url": "https://example.com/sem-01.ics" }
  ]
}
```

See `examples/billboard_config.minimal.json`.

## Top-level (board settings)

| Field | Type | Default | Description |
|---|---|---|---|
| `title` | string | `"Lab Flightboard"` | Header title |
| `subtitle` | string | `"Instrument Status"` | Header subtitle |
| `timezone` | string | `"UTC"` | IANA timezone, e.g. `Australia/Brisbane`. Drives "today" and all displayed times |
| `per_page` | int | `6` | Instruments per screen (the grid is 3 wide × 2 tall) |
| `rotate_seconds` | int | `20` | Seconds between pages when there are more instruments than `per_page` |
| `refresh_seconds` | int | `60` | How often the board re-fetches feeds |
| `incident_lookahead_days` | int | `30` | How far ahead to look for upcoming incidents |
| `mode` | string | `"full"` | `"full"` (show bookings) or `"status-only"` (availability only) |
| `incident_categories` | string[] | `["Incident","Intervention","Maintenance","Down"]` | iCal CATEGORIES values that mark an event as an incident |
| `incident_keywords` | string[] | `[]` | Substrings in a title that mark an event as an incident |
| `incident_link_patterns` | string[] | `["/inc/"]` | Substrings in an event's URL/description that mark it as an incident (how many facility booking systems flag incidents) |
| `display_options` | object | see below | Privacy and layout choices |
| `instruments` | object[] | `[]` | The instrument list (see below) |

## `display_options`

| Field | Type | Default | Description |
|---|---|---|---|
| `show_user_id` | bool | `false` | Show a user ID next to each booking (from the organiser email local part). Never sent to the browser when off |
| `show_email` | bool | `false` | Show the organiser email next to each booking. Never sent to the browser when off |
| `name_display` | string | `"full"` | `"full"` shows the whole name; `"initials"` shows e.g. `A. R.` |
| `day_window` | string | `"full"` | `"full"` lists all of today's bookings; `"business"` lists only those overlapping business hours |
| `business_start` | string | `"09:00"` | Start of the business window (`day_window: "business"`) |
| `business_end` | string | `"18:00"` | End of the business window |
| `strip_parentheses` | bool | `true` | Remove `(...)` groups (instrument label, user id) from booking titles so only the person's name shows |

## `instruments[]`

| Field | Type | Required | Description |
|---|---|---|---|
| `equipment_name` | string | yes | Name shown on the tile |
| `calendar_url` | string | no | Booking iCal feed (`https://`, `webcal://`, or `demo://booking`/`demo://free`/`demo://incident`). Empty/missing shows the tile as "no data" |
| `equipment_id` | string | no | Stable internal id; derived from the name when omitted (e.g. `SEM 01` → `sem-01`) |
| `room` | string | no | Room number shown under the instrument name |
| `incident_url` | string | no | Optional **separate** incident feed; all its events are treated as incidents |
| `summary_strip` | string | no | Text to remove from every booking title (the building/instrument label) so only the person shows |
| `display_order` | int | no | Sort order on the board (lower first) |
| `enabled` | bool | no | `false` hides without deleting (default `true`) |
| `incidents_only` | bool | no | Give this entry **no tile**; its feed only contributes incidents/interventions to the scrolling ticker |

---

## How booking names are cleaned

Booking systems often stamp every booking with the building + instrument and a
user id, e.g. `BLDG-A SEM-1 Alex Taylor (BLDG-A SEM-1)`. With `strip_parentheses`
on (the default), the board:

1. removes every `(...)` group (instrument label, `( u1234567 )` user id, …);
2. removes the building/instrument label where it prefixes the title — detecting
   the label that **recurs across the feed**, so bookings whose own parentheses
   only held a user id are cleaned from what their peers reveal.

Result: `Alex Taylor`. If a few still show the prefix, set that instrument's
`summary_strip` to the exact label (e.g. `BLDG-A SEM-2`).

---

## Annotated example

```jsonc
{
  "title": "My Core Facility",
  "subtitle": "Instrument Status",
  "timezone": "Australia/Brisbane",
  "per_page": 6,            // 6 tiles per screen; extras paginate
  "rotate_seconds": 20,     // page rotation interval
  "refresh_seconds": 60,    // feed refresh interval
  "incident_lookahead_days": 30,
  "mode": "full",           // or "status-only" for public screens
  "incident_categories": ["Incident", "Intervention", "Maintenance", "Down"],
  "incident_keywords": ["fault", "offline", "out of service"],
  "incident_link_patterns": ["/inc/"],  // how many booking systems flag incidents
  "display_options": {
    "show_user_id": false,
    "show_email": false,
    "name_display": "full", // or "initials"
    "day_window": "full",   // or "business"
    "business_start": "09:00",
    "business_end": "18:00",
    "strip_parentheses": true
  },
  "instruments": [
    {
      "equipment_id": "sem-01",
      "equipment_name": "SEM 01",
      "room": "Room 1.01",
      "calendar_url": "https://example.com/sem-01.ics",
      "summary_strip": "BLDG-A SEM-1",
      "display_order": 1
    },
    {
      "equipment_id": "facility-incidents",
      "equipment_name": "Facility Incidents",
      "calendar_url": "https://example.com/incidents.ics",
      "incidents_only": true   // no tile; feeds the ticker only
    }
  ]
}
```

> `jsonc` comments above are for illustration only — real JSON does not allow
> comments. The form output is plain JSON.

---

## Applying changes

- **Live (no restart):** edit at `/config`, click **Save to server & apply**.
- **Manual:** edit `billboard_config.json`, then restart the app (or
  `sudo systemctl restart flightboard.service` on a Pi).

See [billboard.md](billboard.md#saving-changes-and-restarting) for details.
