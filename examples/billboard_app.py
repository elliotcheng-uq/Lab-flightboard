# -*- coding: utf-8 -*-
"""
Lab Flightboard - Instrument Status Billboard
=============================================
An airport-departure-board style status display for shared lab instruments,
designed for a wall-mounted TV driven by a Raspberry Pi (or any PC).

For each instrument it reads an iCal booking feed and shows:
  - Today's bookings (time + person), with the current session highlighted
  - A solid colour for the whole tile by live status:
        GREEN  = free now (available)
        ORANGE = in use now
        RED    = down (active incident / intervention)
  - Active and upcoming incidents in a scrolling ticker along the bottom

Display-only. No logins, no SSH, no file transfer. It only reads iCal feeds.

This file is a TEMPLATE. It ships with built-in placeholder instruments and
demo bookings (the "demo://" feeds below) so you can see the design immediately.
Replace them with your own instruments by editing a billboard_config.json file
(see examples/billboard_config.example.json) - a future web admin form will
write that same file.

Requirements:
    pip install -e .          (installs the lab_flightboard package)
    pip install flask

Run:
    python examples/billboard_app.py [path/to/billboard_config.json]
    Open http://localhost:5200   (press F11 for full screen on the TV)

All source is kept ASCII-safe for Windows embeddable Python.
"""
import os
import sys
import concurrent.futures
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify

from lab_flightboard import (
    BillboardConfigError,
    build_instrument_view,
    clean_title,
    is_active,
    load_billboard_config,
    parse_billboard_config,
    parse_events_from_calendar,
    parse_ical_bytes,
    parse_occurrences_from_url,
)
from lab_flightboard.billboard import InstrumentView
from lab_flightboard.billboard_config import enabled_instruments

app = Flask(__name__)

HTTP_PORT = int(os.environ.get("LAB_FLIGHTBOARD_PORT", "5200"))

# Where to look for the config: CLI arg > env var > ./billboard_config.json >
# the bundled example (placeholder instruments + demo feeds).
_EXAMPLE_CONFIG = Path(__file__).parent / "billboard_config.example.json"


def _resolve_config_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    env = os.environ.get("LAB_FLIGHTBOARD_CONFIG")
    if env:
        return Path(env)
    local = Path.cwd() / "billboard_config.json"
    if local.exists():
        return local
    return _EXAMPLE_CONFIG


def load_config():
    path = _resolve_config_path()
    if path == _EXAMPLE_CONFIG:
        print("  No billboard_config.json found - using bundled PLACEHOLDER demo config.")
        print("  Copy examples/billboard_config.example.json to billboard_config.json and edit it.")
    cfg = load_billboard_config(path)
    return cfg


# ==============================================================================
# Placeholder / demo feeds
# ==============================================================================
# The example config points instruments at "demo://booking", "demo://free" and
# "demo://incident". These are generated in-process (no network) so the board
# shows a live, colourful layout straight away. Real instruments use https URLs.

def _ics_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_demo_feed(kind: str, now: datetime) -> bytes:
    """Generate a tiny ICS feed for placeholder instruments."""
    def vevent(uid, start, end, summary, categories=None):
        lines = [
            "BEGIN:VEVENT",
            "UID:" + uid,
            "DTSTAMP:" + _ics_dt(now),
            "DTSTART:" + _ics_dt(start),
            "DTEND:" + _ics_dt(end),
            "SUMMARY:" + summary,
        ]
        if categories:
            lines.append("CATEGORIES:" + categories)
        lines.append("END:VEVENT")
        return "\r\n".join(lines)

    events = []
    if kind == "booking":
        events.append(vevent("demo-b1@local", now - timedelta(hours=1),
                             now + timedelta(hours=1), "A. Researcher (DEMO)"))
        events.append(vevent("demo-b2@local", now + timedelta(hours=2),
                             now + timedelta(hours=3), "B. Student (DEMO)"))
    elif kind == "free":
        events.append(vevent("demo-f1@local", now + timedelta(hours=3),
                             now + timedelta(hours=4), "C. User (DEMO)"))
    elif kind == "incident":
        events.append(vevent("demo-i1@local", now - timedelta(minutes=30),
                             now + timedelta(days=2),
                             "Vacuum system fault - awaiting engineer", "Incident"))

    head = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Lab Flightboard//Demo//EN",
        "X-WR-CALNAME:Demo Feed",
    ]
    return ("\r\n".join(head + events + ["END:VCALENDAR"]) + "\r\n").encode()


# ==============================================================================
# Per-instrument fetch
# ==============================================================================

def occurrences_for_url(url, equipment_id, equipment_name, start, end, now):
    """Return CalendarBooking occurrences for a real URL or a demo:// feed."""
    if url.startswith("demo://"):
        kind = url[len("demo://"):]
        cal = parse_ical_bytes(make_demo_feed(kind, now))
        return parse_events_from_calendar(cal, equipment_id, equipment_name, url)
    return parse_occurrences_from_url(url, equipment_id, equipment_name, start, end)


def load_instrument(inst, config, tz, now, start, end):
    try:
        booking_events = occurrences_for_url(
            inst.calendar_url, inst.equipment_id, inst.equipment_name, start, end, now
        )
        incident_events = []
        if inst.incident_url:
            incident_events = occurrences_for_url(
                inst.incident_url, inst.equipment_id, inst.equipment_name, start, end, now
            )
        view = build_instrument_view(
            inst.equipment_id, inst.equipment_name,
            booking_events, incident_events, now, tz,
            config.incident_categories, config.incident_keywords,
        )
    except Exception as exc:
        view = InstrumentView(inst.equipment_id, inst.equipment_name, "nodata", error=str(exc))
    return _serialize(view, config, inst, tz, now)


def _fmt_hm(dt, tz):
    return dt.astimezone(tz).strftime("%H:%M")


def _fmt_full(dt, tz):
    return dt.astimezone(tz).strftime("%a %d %b %H:%M")


def _serialize(view, config, inst, tz, now):
    d = {
        "name": view.equipment_name,
        "status": view.status,
        "error": view.error,
        "incidents": [
            {
                "title": clean_title(i.title, inst.summary_strip),
                "start": _fmt_full(i.start, tz),
                "end": _fmt_full(i.end or i.start, tz),
                "active": is_active(i, now),
            }
            for i in view.incidents
        ],
    }
    # In status-only mode we deliberately do NOT send booking names/times to the
    # browser - the tile shows availability only, the ticker shows incidents.
    if config.mode == "full":
        d["bookings"] = [
            {
                "name": clean_title(b.title, inst.summary_strip),
                "start": _fmt_hm(b.start, tz),
                "end": _fmt_hm(b.end, tz) if b.end else "",
                "active": is_active(b, now),
            }
            for b in view.bookings
        ]
    else:
        d["bookings"] = []
    return d


def fetch_all(config):
    tz = ZoneInfo(config.timezone) if ZoneInfo else timezone.utc
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now + timedelta(days=config.incident_lookahead_days)

    instruments = enabled_instruments(config)
    if not instruments:
        return []
    workers = max(1, min(12, len(instruments)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(
            lambda inst: load_instrument(inst, config, tz, now, start, end),
            instruments,
        ))


# ==============================================================================
# Frontend (single embedded page, sized in vw units so it scales to any TV)
# ==============================================================================
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ - Instrument Status</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  background: #05070f; color: #fff;
  font-family: "Segoe UI", system-ui, Arial, sans-serif;
  overflow: hidden; display: flex; flex-direction: column;
}
.topbar {
  flex: 0 0 auto; background: #0a0e1c; border-bottom: 2px solid #1b2340;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.7vw 1.6vw;
}
.brand { display: flex; align-items: baseline; gap: 1vw; }
.brand .b1 { font-size: 1.9vw; font-weight: 800; letter-spacing: 0.04em; }
.brand .b2 { font-size: 1.0vw; font-weight: 600; color: #7f8bb5; letter-spacing: 0.16em;
             text-transform: uppercase; }
.topright { display: flex; align-items: baseline; gap: 1.6vw; }
.page-ind { font-size: 1.0vw; font-weight: 700; color: #8d97c0;
            background: #141a30; padding: 0.25vw 0.8vw; border-radius: 0.5vw; }
.clock { font-size: 2.1vw; font-weight: 800; font-variant-numeric: tabular-nums;
         letter-spacing: 0.03em; }
.datestr { font-size: 0.95vw; font-weight: 600; color: #8d97c0; }

.board-wrap { flex: 1 1 auto; min-height: 0; }
.board {
  height: 100%; display: grid;
  grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(2, 1fr);
  gap: 0.9vw; padding: 0.9vw 1.1vw;
}
.panel {
  border-radius: 1vw; padding: 1.0vw 1.3vw; display: flex; flex-direction: column;
  overflow: hidden; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.10);
  transition: background 0.4s;
}
.panel.free   { background: #18803f; }
.panel.inuse  { background: #d97a16; }
.panel.down   { background: #c01f1f; }
.panel.nodata { background: #3a3f52; }

.panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.8vw; }
.panel-name { font-size: 1.75vw; font-weight: 800; line-height: 1.05;
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.panel-status { font-size: 1.5vw; font-weight: 800; letter-spacing: 0.05em;
                white-space: nowrap; opacity: 0.95; }

.bookings { margin-top: 0.7vw; display: flex; flex-direction: column;
            gap: 0.35vw; overflow: hidden; }
.brow { display: flex; align-items: baseline; gap: 0.8vw;
        background: rgba(0,0,0,0.18); border-radius: 0.4vw;
        padding: 0.3vw 0.7vw; font-size: 1.12vw; }
.brow.now { background: rgba(255,255,255,0.26); font-weight: 800; }
.btime { font-variant-numeric: tabular-nums; white-space: nowrap; }
.bname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.note-line { margin-top: 0.7vw; font-size: 1.05vw; font-weight: 600; opacity: 0.85; }
.status-big { margin: auto 0; font-size: 2.6vw; font-weight: 800; opacity: 0.92; }
.down-reason { margin-top: 0.8vw; font-size: 1.55vw; font-weight: 800; line-height: 1.15; }
.down-dates  { margin-top: 0.4vw; font-size: 1.05vw; font-weight: 600; opacity: 0.9; }

.ticker {
  flex: 0 0 auto; height: 3.2vw; background: #0a0e1c; border-top: 2px solid #1b2340;
  display: flex; align-items: center; overflow: hidden; white-space: nowrap;
}
.ticker-label {
  flex: 0 0 auto; background: #c01f1f; color: #fff; font-size: 1.0vw; font-weight: 800;
  letter-spacing: 0.08em; height: 100%; display: flex; align-items: center; padding: 0 1.1vw;
}
.ticker-mask { flex: 1 1 auto; overflow: hidden; }
.ticker-track {
  display: inline-block; white-space: nowrap; padding-left: 100%;
  font-size: 1.15vw; font-weight: 600; color: #ffd35a;
  animation: scroll-left 38s linear infinite;
}
.ticker-track.calm { color: #6fd38a; }
@keyframes scroll-left { to { transform: translateX(-100%); } }
.tk-inst { color: #fff; font-weight: 800; }
.tk-sep  { color: #45507a; padding: 0 1.0vw; }
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    <span class="b1">__TITLE__</span>
    <span class="b2">__SUBTITLE__</span>
  </div>
  <div class="topright">
    <span class="page-ind" id="page-ind" style="display:none"></span>
    <div style="text-align:right">
      <div class="clock" id="clock">--:--:--</div>
      <div class="datestr" id="datestr"></div>
    </div>
  </div>
</div>

<div class="board-wrap" id="board-wrap">
  <div class="board"></div>
</div>

<div class="ticker">
  <div class="ticker-label">INCIDENTS</div>
  <div class="ticker-mask">
    <div class="ticker-track calm" id="ticker">Loading instrument status...</div>
  </div>
</div>

<script>
var PER_PAGE   = __PER_PAGE__;
var ROTATE_MS  = __ROTATE_MS__;
var REFRESH_MS = __REFRESH_MS__;
var MODE       = "__MODE__";

var STATUS_WORD = { free: 'FREE', inuse: 'IN USE', down: 'DOWN', nodata: 'NO DATA' };
var pages = [];
var curPage = 0;

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
                  .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

var DAYS   = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function pad(n) { return (n < 10 ? '0' : '') + n; }
function tick() {
  var d = new Date();
  document.getElementById('clock').textContent =
    pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  document.getElementById('datestr').textContent =
    DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
}
setInterval(tick, 1000); tick();

function panelHTML(inst) {
  var st = inst.status || 'nodata';
  var h = '<div class="panel ' + st + '">';
  h += '<div class="panel-head">';
  h += '<div class="panel-name">' + esc(inst.name) + '</div>';
  h += '<div class="panel-status">' + (STATUS_WORD[st] || '') + '</div>';
  h += '</div>';

  if (st === 'down') {
    var inc = (inst.incidents && inst.incidents.length) ? inst.incidents[0] : null;
    h += '<div class="down-reason">' + (inc ? esc(inc.title) : 'Unavailable') + '</div>';
    if (inc) h += '<div class="down-dates">until ' + esc(inc.end) + '</div>';
  } else if (MODE === 'status-only') {
    h += '<div class="status-big">' + (st === 'inuse' ? 'In use' : st === 'nodata' ? 'No data' : 'Available') + '</div>';
  } else {
    h += '<div class="bookings">';
    if (inst.error) {
      h += '<div class="note-line">calendar unavailable</div>';
    } else if (!inst.bookings || !inst.bookings.length) {
      h += '<div class="note-line">No bookings today</div>';
    } else {
      for (var i = 0; i < inst.bookings.length; i++) {
        var b = inst.bookings[i];
        h += '<div class="brow' + (b.active ? ' now' : '') + '">';
        h += '<span class="btime">' + esc(b.start) + '-' + esc(b.end) + '</span>';
        h += '<span class="bname">' + esc(b.name) + '</span>';
        h += '</div>';
      }
    }
    h += '</div>';
  }
  h += '</div>';
  return h;
}

function drawPage() {
  var wrap = document.getElementById('board-wrap');
  var page = pages[curPage] || [];
  var h = '<div class="board">';
  for (var i = 0; i < page.length; i++) h += panelHTML(page[i]);
  h += '</div>';
  wrap.innerHTML = h;
  var ind = document.getElementById('page-ind');
  if (pages.length > 1) {
    ind.style.display = '';
    ind.textContent = (curPage + 1) + ' / ' + pages.length;
  } else {
    ind.style.display = 'none';
  }
}

function buildTicker(data) {
  var parts = [];
  for (var i = 0; i < data.length; i++) {
    var s = data[i];
    if (s.incidents && s.incidents.length) {
      for (var j = 0; j < s.incidents.length; j++) {
        var inc = s.incidents[j];
        var tag = inc.active ? 'NOW' : 'from ' + esc(inc.start);
        parts.push('<span class="tk-inst">' + esc(s.name) + ':</span> '
                   + esc(inc.title) + ' (' + tag + ' until ' + esc(inc.end) + ')');
      }
    }
  }
  var t = document.getElementById('ticker');
  if (!parts.length) {
    t.className = 'ticker-track calm';
    t.innerHTML = 'All instruments operating normally';
  } else {
    t.className = 'ticker-track';
    t.innerHTML = parts.join('<span class="tk-sep">+++</span>');
  }
}

function render(data) {
  pages = [];
  for (var i = 0; i < data.length; i += PER_PAGE) pages.push(data.slice(i, i + PER_PAGE));
  if (curPage >= pages.length) curPage = 0;
  drawPage();
  buildTicker(data);
}

setInterval(function () {
  if (pages.length > 1) {
    curPage = (curPage + 1) % pages.length;
    drawPage();
  }
}, ROTATE_MS);

function load() {
  fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) render(d.instruments);
  }).catch(function () {});
}
load();
setInterval(load, REFRESH_MS);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    cfg = app.config["BILLBOARD"]
    page = (HTML
            .replace("__TITLE__", cfg.title)
            .replace("__SUBTITLE__", cfg.subtitle)
            .replace("__PER_PAGE__", str(cfg.per_page))
            .replace("__ROTATE_MS__", str(cfg.rotate_seconds * 1000))
            .replace("__REFRESH_MS__", str(cfg.refresh_seconds * 1000))
            .replace("__MODE__", cfg.mode))
    return page


@app.route("/api/status")
def api_status():
    cfg = app.config["BILLBOARD"]
    return jsonify({"ok": True, "instruments": fetch_all(cfg)})


def main():
    try:
        cfg = load_config()
    except BillboardConfigError as exc:
        print("  Config error: " + str(exc))
        sys.exit(1)
    app.config["BILLBOARD"] = cfg

    print("")
    print("  Lab Flightboard - Instrument Status Billboard")
    print("  ---------------------------------------------")
    print("  Title       : " + cfg.title)
    print("  Mode        : " + cfg.mode)
    print("  Instruments : " + str(len(enabled_instruments(cfg))))
    print("  Per screen  : " + str(cfg.per_page) + "  (rotate every " + str(cfg.rotate_seconds) + "s if more)")
    print("  Refresh     : every " + str(cfg.refresh_seconds) + "s")
    print("")
    print("  Open http://localhost:" + str(HTTP_PORT) + " and press F11 for full screen")
    print("")
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False)


if __name__ == "__main__":
    main()
