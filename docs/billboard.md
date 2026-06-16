# Billboard Display Guide

The billboard is an **airport-departure-board style** status display for shared
lab instruments. It is the end-goal of Lab Flightboard: a large-screen wall
display, typically driven by a Raspberry Pi, that anyone can stand up by pointing
it at their own iCal feeds.

It is **display-only** — no logins, no SSH, no file transfer. It only reads iCal
calendar feeds.

---

## The design

```
+-------------------------------------------------------------------------+
|  LAB FLIGHTBOARD   Instrument Status            1 / 2     14:32:07       |
|                                                          Mon 15 Jun 2026 |
+-------------------------+-------------------------+-----------------------+
|  SEM 01        IN USE   |  SEM 02         FREE    |  TEM 01        DOWN    |
|  09:00-11:00 A. Smith   |  No bookings today      |  Vacuum system fault  |
|  13:00-15:00 B. Jones   |                         |  until Wed 17 Jun     |
+-------------------------+-------------------------+-----------------------+
|  FIB-SEM       IN USE   |  XRD 01         FREE    |  AFM 01        FREE    |
|  10:00-12:00 C. Lee     |  15:00-16:00 D. Park    |  No bookings today    |
+-------------------------+-------------------------+-----------------------+
| INCIDENTS  TEM 01: Vacuum system fault (NOW until Wed 17 Jun 09:00) +++  |
+-------------------------------------------------------------------------+
```

**Each tile is one instrument**, solid-coloured by live status:

| Colour | Status | Meaning |
|---|---|---|
| **Green** | `free` | Available now |
| **Orange** | `inuse` | A booking is active right now |
| **Red** | `down` | An active incident / intervention |
| **Grey** | `nodata` | The feed could not be fetched |

Other elements:

- **Today's bookings** are listed on each tile (time + person); the current
  session is highlighted.
- An **at-a-glance summary** headlines each tile — "Free until 13:00",
  "In use until 15:00", or "Available all day".
- A scrolling **incident ticker** runs along the bottom showing active and
  upcoming incidents across all instruments.
- A live **clock + date** and a **last-updated** time sit top-right, so you can
  confirm the board is live.
- If you have more instruments than fit on one screen (default 6, a 3x2 grid),
  the board **paginates and rotates** automatically, with a `1 / 2` indicator.
- **Long names scroll** sideways and **busy tiles scroll** their booking list
  vertically, so nothing is cut off no matter how long the name or how full the
  day.

---

## Run it

From the repo root:

```bash
pip install -e .
pip install flask
python examples/billboard_app.py
```

Then open `http://localhost:5200` and press **F11** for full screen.

With **no config file present**, it runs on built-in **placeholder instruments**
with **demo bookings** (the `demo://` feeds), so you see the full design working
immediately — green, orange and red tiles plus a live incident ticker. This is
the design scaffold that a future user-entry form will replace.

On Windows you can instead double-click **`start-billboard.bat`**, which starts
the server and opens the display in Edge kiosk mode.

---

## Build your config in the browser (no JSON by hand)

There is a fill-in-the-blanks form for producing `billboard_config.json`:

- Open `examples/config_builder.html` directly in any browser, **or**
- With the server running, visit `http://localhost:5200/config`.

It has fields for the board settings (title, timezone, **instruments per
screen** and the **rotate-every-N-seconds** scroll), all the display options
below, and a freeform **Add instrument** list. Click **Download
billboard_config.json** (or **Copy**) and drop the file next to the app. You can
also paste an existing config back in to edit it.

### Bulk import from a list of iCal links

In the form's **Bulk import from iCal links** box, paste one iCal URL per line
and click **Import & detect**. The server fetches each feed and adds an
instrument row with the **name** pre-filled (from the feed's calendar name
`X-WR-CALNAME`, or the building/instrument label that recurs across its
bookings) and the **room** (from `LOCATION`) when present. Names are a best guess
- some feeds use generic calendar names - so review and edit the rows, then
**Save to server & apply**. Feeds that fail to fetch are reported and skipped, so
one bad link doesn't stop the rest. (Bulk import needs the page open at
`/config`, since it asks the server to fetch the feeds.)

## Saving changes and restarting

The server reads the config on every status poll, so there are two ways to apply
an edit:

**Apply live from the form (no restart).** Open `http://localhost:5200/config`,
make your changes, and click **Save to server & apply**. The server validates the
config, writes `billboard_config.json`, and hot-swaps it in place — the board
updates on its next refresh (within `refresh_seconds`). Use **Load current server
config** to pull the running config back into the form first. (This only works
when the page is opened from the running server, not as a `file://`.)

> On an untrusted network, start the server with `LAB_FLIGHTBOARD_READONLY=1` to
> disable saving from the form. The board still runs; `/api/config` returns 403
> on writes.

**Manual restart.** If you edit `billboard_config.json` by hand:

1. Stop the server: **Ctrl+C** in its terminal (or close the
   "Lab Flightboard Server" window).
2. Save your `billboard_config.json` in the working directory.
3. Start it again: `python examples/billboard_app.py`.

On a Raspberry Pi running under systemd, apply a hand-edit with
`sudo systemctl restart flightboard.service` (see the deployment guide). The
live-apply form works there too.

## The simplest possible config

Most fields are optional. The smallest useful config is just a name + URL per
instrument (`equipment_id` is derived from the name, everything else uses
sensible defaults). See `examples/billboard_config.minimal.json`:

```json
{
  "title": "My Lab",
  "timezone": "Australia/Brisbane",
  "instruments": [
    { "equipment_name": "SEM 01", "room": "Room 101", "calendar_url": "https://example.com/sem-01.ics" },
    { "equipment_name": "TEM 01", "room": "Room 102", "calendar_url": "https://example.com/tem-01.ics" },
    { "equipment_name": "Facility Incidents", "calendar_url": "https://example.com/incidents.ics", "incidents_only": true }
  ]
}
```

A missing or empty `calendar_url` just shows that tile as "no data" — it never
crashes the board.

## Add your own instruments

Copy an example and edit it (or use the form above):

```bash
cp examples/billboard_config.minimal.json billboard_config.json   # or .example.json for all options
```

`billboard_config.json` is **git-ignored** — your private feed URLs never get
committed. The app loads it automatically from the working directory (or pass a
path: `python examples/billboard_app.py path/to/config.json`).

### Config reference

```json
{
  "title": "My Core Facility",
  "subtitle": "Instrument Status",
  "timezone": "Australia/Brisbane",
  "per_page": 6,
  "rotate_seconds": 20,
  "refresh_seconds": 60,
  "incident_lookahead_days": 30,
  "mode": "full",
  "incident_categories": ["Incident", "Intervention", "Maintenance", "Down"],
  "incident_keywords": ["fault", "offline", "out of service"],
  "instruments": [
    {
      "equipment_id": "sem-01",
      "equipment_name": "SEM 01",
      "calendar_url": "https://example.com/sem-01.ics",
      "incident_url": null,
      "summary_strip": "SEM 01",
      "display_order": 1,
      "enabled": true
    }
  ]
}
```

**Global settings**

| Field | Default | Description |
|---|---|---|
| `title` / `subtitle` | "Lab Flightboard" / "Instrument Status" | Header text |
| `timezone` | `"UTC"` | IANA name, e.g. `Australia/Brisbane`. Used for "today" and time display |
| `per_page` | `6` | Tiles per screen (the grid is 3 wide x 2 tall) |
| `rotate_seconds` | `20` | Page rotation interval when there are more than `per_page` |
| `refresh_seconds` | `60` | How often the board re-fetches feeds |
| `incident_lookahead_days` | `30` | How far ahead to look for upcoming incidents |
| `mode` | `"full"` | `"full"` or `"status-only"` (see below) |
| `incident_categories` | Incident/Intervention/Maintenance/Down | CATEGORIES values that mark an event as an incident |
| `incident_keywords` | `[]` | Substrings in a title that mark an event as an incident |
| `incident_link_patterns` | `["/inc/"]` | Substrings in an event's URL/description that mark it as an incident (how many facility booking systems flag incidents) |

**Display options** (`display_options`)

| Field | Default | Description |
|---|---|---|
| `show_user_id` | `false` | Show a user ID next to each booking (derived from the organiser email's local part) |
| `show_email` | `false` | Show the organiser email next to each booking |
| `name_display` | `"full"` | `"full"` shows the whole name; `"initials"` shows e.g. `A. R.` |
| `day_window` | `"full"` | `"full"` lists all of today's bookings; `"business"` lists only those overlapping business hours |
| `business_start` | `"09:00"` | Start of the business window (used when `day_window` is `"business"`) |
| `business_end` | `"18:00"` | End of the business window |
| `strip_parentheses` | `true` | Remove `(...)` groups (instrument label, user id) from booking titles so only the person's name shows |

> **Booking names are cleaned automatically.** Many systems stamp every booking
> with the building + instrument, e.g.
> `BLDG-A SEM-1 Alex Taylor (BLDG-A SEM-1)`. The board strips the `(...)` groups
> and the repeated building/instrument label (it detects the label that recurs
> across the feed), leaving just `Alex Taylor`. If a few bookings still show the
> prefix, set that instrument's **Strip from titles** (`summary_strip`) to the
> exact building+instrument text, e.g. `BLDG-A SEM-2`.

> `show_user_id` and `show_email` are **off by default**, and when off the
> values are never even sent to the browser. `day_window` only affects which
> bookings are **listed** — an instrument still shows IN USE if a booking is
> active outside the window.

**Per-instrument settings**

| Field | Required | Description |
|---|---|---|
| `equipment_id` | yes | Stable internal id |
| `equipment_name` | yes | Name shown on the tile |
| `room` | no | Room number shown under the instrument name (e.g. `Room 2.14`) |
| `calendar_url` | yes | Booking iCal feed (`https://`, `webcal://`, or `demo://...`) |
| `incident_url` | no | Optional **separate** incident feed; all its events are treated as incidents |
| `summary_strip` | no | Text to remove from every booking title (e.g. the repeated instrument name) so tiles show just the person |
| `display_order` | no | Sort order on the board (lower first) |
| `enabled` | no | Set `false` to hide without deleting (default `true`) |
| `incidents_only` | no | Give this entry **no tile**; its feed only contributes incidents/interventions to the scrolling ticker |

### Incident-only entries

Tick **Incidents & interventions only** on an instrument (or set
`"incidents_only": true`) to add an equipment whose feed should **not** appear as
a calendar tile — its events are surfaced only in the bottom incident ticker.
Use this for a dedicated incident/maintenance calendar, or for equipment where
you want to broadcast outages without showing its bookings on the board.

> `webcal://` URLs are converted to `https://` automatically.

---

## Two display modes

### `full` (default)

Tiles show each booking — time and person — with the current session
highlighted. Best for staff areas.

### `status-only`

Tiles show **only availability** (Available / In use / Down) with no names or
times. The incident ticker still runs along the bottom. The booking details are
**never sent to the browser** in this mode, so it is safe for a public-facing
display where you do not want to show who booked what.

```json
{ "mode": "status-only" }
```

In both modes the **incident ticker** behaves the same — this is how you run a
display that shows *only incidents and interventions* and keeps the calendar
private: set `mode` to `status-only`.

---

## How an instrument turns RED

An instrument shows **DOWN** (red) when it has an **active incident**. An event
in a booking feed is recognised as an incident in any of these ways:

1. **Category.** Its `CATEGORIES` matches one of `incident_categories`
   (e.g. `CATEGORIES:Maintenance`).
2. **Title keyword.** Its title contains one of `incident_keywords`
   (e.g. "Vacuum fault").
3. **Link pattern.** Its URL or description contains one of
   `incident_link_patterns`. Many facility booking systems mark incidents not
   with a category but with a link such as `.../inc/...`, so the default is
   `["/inc/"]`. Add your own patterns (e.g. `/intervention/`) if your system
   uses a different path.
4. **Separate incident feed.** Set `incident_url` on the instrument; every event
   in that feed is treated as an incident.

> If your incidents are not turning tiles red, this is almost always the cause:
> the events are not categorised, so you need the right `incident_link_patterns`
> (or `incident_keywords`) for your booking system. Use
> `python examples/inspect_calendar.py <url>` to see what fields your feed
> actually exposes.

An incident appears on the board while it is active or upcoming (within
`incident_lookahead_days`) and clears itself automatically once it ends — so the
event needs an **end time**. An open-ended incident with no end date will not
show; give it a predicted end date to display it.

---

## Deploying to a wall display

See [deployment_raspberry_pi.md](deployment_raspberry_pi.md) for running the
board on a Raspberry Pi in kiosk mode on boot.

---

## Privacy

- Real iCal URLs may contain private access tokens. They live only in
  `billboard_config.json`, which is git-ignored. **Do not commit it.**
- The parser never logs full URLs — only the scheme and host.
- Use `status-only` mode for any display the public can see.
