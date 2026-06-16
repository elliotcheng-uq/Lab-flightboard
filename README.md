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

## Requirements

- **Python 3.10 or newer** (3.11+ recommended) — includes `pip`
- **Flask** (`pip install flask`) — only needed for the billboard display and the
  config form; the parser itself does not need it
- **Internet access** from the machine that runs it, so it can reach your iCal
  feeds
- A **modern browser** to show the board (Chromium/Chrome/Edge/Firefox)

No database, no accounts, no build step, no cloud service. It is a single Python
process serving one web page, plus a small library. To deploy it on a wall TV see
the [Raspberry Pi guide](docs/deployment_raspberry_pi.md).

Python libraries (installed automatically by the step below): `icalendar`,
`recurring-ical-events`, `python-dateutil`, `requests`.

## Setup (run on your computer)

```bash
# 1. Get the code
git clone https://github.com/elliotcheng-uq/Lab-flightboard.git
cd Lab-flightboard

# 2. Install the package and Flask
pip install -e .
pip install flask

# 3. Start the billboard
python examples/billboard_app.py
```

Then open **`http://localhost:5200`** and press **F11** for full screen.

> **Windows:** if `python` opens the Microsoft Store, use `py` instead
> (`py examples\billboard_app.py`), or double-click **`serve.bat`** /
> **`start-billboard.bat`** which also opens the display full-screen.

With no config present it runs on **placeholder instruments with demo bookings**,
so you see the full design immediately — green (free), orange (in use) and red
(down) tiles plus a scrolling incident ticker.

## Configure your instruments

```bash
cp examples/billboard_config.minimal.json billboard_config.json   # git-ignored
# edit billboard_config.json: replace the URLs with your iCal feeds
```

Each instrument needs only a name and a calendar URL; everything else has a
sensible default. Restart the app (or use the browser form below) to apply.
See `examples/billboard_config.example.json` for every option.

### Edit it in the browser (no JSON by hand)

Visit **`http://localhost:5200/config`** while the app runs (or open
`examples/config_builder.html` directly). The form covers every setting, and
**Save to server & apply** writes `billboard_config.json` and applies it live —
no restart. Use **Load current server config** to pull the running config back
into the form.

**Bulk import:** paste a list of iCal URLs (one per line) and the form fetches
each feed and pre-fills a row — instrument name (from the feed's calendar name)
and room — ready for you to edit before saving.

### Key billboard features

- **Live colour-coded tiles** — green (free), orange (in use), red (down) — in a
  3×2 grid that paginates/rotates when you have more instruments than fit.
- **Scrolling incident ticker** along the bottom for active and upcoming
  incidents/interventions.
- **Room number** shown under each instrument name.
- **At-a-glance summary** per tile ("Free until 13:00" / "In use until 15:00")
  and a **last-updated** time so you can see the board is live.
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
pip install -e ".[dev]"   # installs pytest
pytest
```

The tests use fake/demo feeds only and need no internet access.

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
