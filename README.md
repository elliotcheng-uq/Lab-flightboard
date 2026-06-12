# Lab Flightboard

Airport-style dashboard for lab equipment bookings, instrument status, and incident alerts.

Lab Flightboard reads iCal/ICS feeds from booking systems (PPMS or similar) and
turns them into a large-screen, **airport-departure-board style** status display
for shared lab instruments — designed to run on a Raspberry Pi driving a wall TV.

It has two layers:

1. **A robust iCal parser** (`lab_flightboard` package) — fetch, parse, and
   normalise bookings into clean Python objects.
2. **A billboard display** (`examples/billboard_app.py`) — a config-driven,
   colour-coded board with a live incident ticker. Freeform: anyone points it at
   their own instruments and iCal URLs.

## Install

```bash
pip install -e ".[dev]"
```

## See the billboard now

```bash
pip install flask
python examples/billboard_app.py
# open http://localhost:5200  (press F11 for full screen)
```

With no config present it runs on **placeholder instruments with demo bookings**,
so you see the full design immediately — green (free), orange (in use) and red
(down) tiles plus a scrolling incident ticker. Then add your own instruments:

```bash
cp examples/billboard_config.example.json billboard_config.json   # git-ignored
# edit billboard_config.json: replace demo:// feeds with your iCal URLs
```

### Edit it in the browser (no JSON by hand)

Visit **`http://localhost:5200/config`** while the app runs (or open
`examples/config_builder.html` directly). The form covers every setting, and
**Save to server & apply** writes `billboard_config.json` and applies it live —
no restart. Use **Load current server config** to pull the running config back
into the form.

### Key billboard features

- **Live colour-coded tiles** — green (free), orange (in use), red (down) — in a
  3×2 grid that paginates/rotates when you have more instruments than fit.
- **Scrolling incident ticker** along the bottom for active and upcoming
  incidents/interventions.
- **Room number** shown under each instrument name.
- **Auto-cleaned booking names** — strips the building + instrument and user-id
  text that booking systems stamp on every title, leaving just the person.
- **Display options:** show/hide user ID & email, full name vs initials,
  full-day vs business-hours, instruments-per-screen and rotate interval.
- **Incidents-only entries** — equipment that feeds the ticker only, with no tile.
- **Long names and busy tiles auto-scroll** so nothing is cut off.
- **Two modes:** `full` (show bookings) or `status-only` (public screens — no
  names/times, incidents still scroll).

See **[docs/billboard.md](docs/billboard.md)** for the full config reference and
display modes, and **[docs/deployment_raspberry_pi.md](docs/deployment_raspberry_pi.md)**
for running it on a Pi in kiosk mode.

## Parser quick start

```bash
# Inspect a calendar feed (what fields does it expose?)
python examples/inspect_calendar.py "https://example.com/calendar.ics"

# Parse a single calendar
python examples/parse_single_calendar.py sem-01 "SEM 01" "https://example.com/sem.ics"

# Parse multiple calendars from a JSON config
python examples/parse_multiple_calendars.py examples/equipment_config.json

# Browser-based parser tester (paste a URL or upload an .ics)
python examples/dev_server.py        # http://localhost:5050
```

## Run tests

```bash
pytest
```

## Documentation

| Doc | What it covers |
|---|---|
| [docs/billboard.md](docs/billboard.md) | The display design, config reference, display options, modes, incident detection, applying changes |
| [docs/deployment_raspberry_pi.md](docs/deployment_raspberry_pi.md) | Running the board on a Raspberry Pi (systemd + Chromium kiosk) |
| [docs/field_extraction.md](docs/field_extraction.md) | How instrument, date/time, user, and incident fields are pulled from iCal |
| [docs/config_reference.md](docs/config_reference.md) | Every `billboard_config.json` field in one place, with an annotated example |

## Display modes

| Mode | Tiles show | Use for |
|---|---|---|
| `full` | Availability + each booking (time + person) | Staff areas |
| `status-only` | Availability only — no names/times; incidents still scroll | Public-facing screens |

In `status-only` mode booking details are never sent to the browser, so it shows
**only incidents and interventions** (as the rolling ticker) while keeping the
calendar private.

## Privacy

- Calendar URLs may contain private access tokens. They live only in
  `billboard_config.json`, which is **git-ignored** — never commit it. Commit
  `examples/billboard_config.example.json` (which uses `example.com` / `demo://`
  placeholders) instead.
- The parser never logs full URLs — only the scheme and host.
- Sample/test data uses fake feeds only and requires no internet access.
