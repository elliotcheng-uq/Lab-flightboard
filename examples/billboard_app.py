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
import json
import concurrent.futures
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, request

from lab_flightboard import (
    BillboardConfigError,
    auto_strip_terms,
    build_instrument_view,
    clean_title,
    email_local_part,
    format_name,
    is_active,
    load_billboard_config,
    overlaps_business,
    parse_billboard_config,
    parse_events_from_calendar,
    parse_ical_bytes,
    parse_occurrences_from_url,
)
from lab_flightboard.billboard import InstrumentView
from lab_flightboard.billboard_config import enabled_instruments

app = Flask(__name__)

HTTP_PORT = int(os.environ.get("LAB_FLIGHTBOARD_PORT", "5200"))

# Set LAB_FLIGHTBOARD_READONLY=1 to forbid the /config form from writing the
# config file (recommended if the board is on an untrusted network).
ALLOW_WRITE = os.environ.get("LAB_FLIGHTBOARD_READONLY", "").lower() not in ("1", "true", "yes")

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


def _save_target(load_path: Path) -> Path:
    """Where the /config form writes to. Never overwrite the bundled example."""
    if load_path == _EXAMPLE_CONFIG:
        return Path.cwd() / "billboard_config.json"
    return load_path


def load_config():
    """Return (config, save_path). save_path is where edits are written back."""
    path = _resolve_config_path()
    if path == _EXAMPLE_CONFIG:
        print("  No billboard_config.json found - using bundled PLACEHOLDER demo config.")
        print("  Copy examples/billboard_config.example.json to billboard_config.json and edit it.")
    cfg = load_billboard_config(path)
    return cfg, _save_target(path)


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
    def vevent(uid, start, end, summary, categories=None, organiser=None):
        lines = [
            "BEGIN:VEVENT",
            "UID:" + uid,
            "DTSTAMP:" + _ics_dt(now),
            "DTSTART:" + _ics_dt(start),
            "DTEND:" + _ics_dt(end),
            "SUMMARY:" + summary,
        ]
        if organiser:
            lines.append("ORGANIZER:mailto:" + organiser)
        if categories:
            lines.append("CATEGORIES:" + categories)
        lines.append("END:VEVENT")
        return "\r\n".join(lines)

    events = []
    if kind == "booking":
        # Several bookings (some overflow the tile -> vertical auto-scroll), and
        # a deliberately long name to demonstrate horizontal name scrolling.
        events.append(vevent("demo-b1@local", now - timedelta(hours=1),
                             now + timedelta(hours=1), "Alice Researcher (DEMO)",
                             organiser="alice.researcher@example.edu"))
        events.append(vevent("demo-b2@local", now + timedelta(hours=1),
                             now + timedelta(hours=2), "Bob Student (DEMO)",
                             organiser="bob.student@example.edu"))
        events.append(vevent("demo-b3@local", now + timedelta(hours=2),
                             now + timedelta(hours=3),
                             "Wolfgang Amadeus Vandersloot-Featherington (DEMO)",
                             organiser="wolfgang.vandersloot@example.edu"))
        events.append(vevent("demo-b4@local", now + timedelta(hours=3),
                             now + timedelta(hours=4), "Dana Lee (DEMO)",
                             organiser="dana.lee@example.edu"))
        events.append(vevent("demo-b5@local", now + timedelta(hours=4),
                             now + timedelta(hours=5), "Evan Kim (DEMO)",
                             organiser="evan.kim@example.edu"))
    elif kind == "free":
        events.append(vevent("demo-f1@local", now + timedelta(hours=3),
                             now + timedelta(hours=4), "Carol Nanofab (DEMO)",
                             organiser="carol.nanofab@example.edu"))
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
    strip_terms = [inst.summary_strip] if inst.summary_strip else []
    try:
        feed_events = occurrences_for_url(
            inst.calendar_url, inst.equipment_id, inst.equipment_name, start, end, now
        )
        incident_events = []
        if inst.incident_url:
            incident_events = occurrences_for_url(
                inst.incident_url, inst.equipment_id, inst.equipment_name, start, end, now
            )
        # Auto-detect the building/instrument label that repeats across this
        # feed, so it is stripped from every booking name without configuration.
        titles = [e.title for e in feed_events] + [e.title for e in incident_events]
        strip_terms = strip_terms + auto_strip_terms(titles)

        if inst.incidents_only:
            # No tile: the whole feed feeds the incident ticker only.
            incident_events = list(feed_events) + list(incident_events)
            feed_events = []

        view = build_instrument_view(
            inst.equipment_id, inst.equipment_name,
            feed_events, incident_events, now, tz,
            config.incident_categories, config.incident_keywords,
        )
    except Exception as exc:
        view = InstrumentView(inst.equipment_id, inst.equipment_name, "nodata", error=str(exc))
    return _serialize(view, config, inst, tz, now, strip_terms)


def _fmt_hm(dt, tz):
    return dt.astimezone(tz).strftime("%H:%M")


def _fmt_full(dt, tz):
    return dt.astimezone(tz).strftime("%a %d %b %H:%M")


def _serialize(view, config, inst, tz, now, strip_terms):
    opts = config.display_options
    d = {
        "name": view.equipment_name,
        "room": inst.room,
        "status": view.status,
        "error": view.error,
        "ticker_only": inst.incidents_only,
        "incidents": [
            {
                "title": clean_title(i.title, strip_terms, opts.strip_parentheses),
                "start": _fmt_full(i.start, tz),
                "end": _fmt_full(i.end or i.start, tz),
                "active": is_active(i, now),
            }
            for i in view.incidents
        ],
    }
    # incidents_only entries have no tile; status-only mode hides booking detail.
    if inst.incidents_only or config.mode != "full":
        d["bookings"] = []
        return d

    rows = []
    for b in view.bookings:
        # "9 to 6" option: list only bookings overlapping business hours.
        if opts.day_window == "business" and not overlaps_business(
            b, tz, opts.business_start, opts.business_end
        ):
            continue
        row = {
            "name": format_name(
                clean_title(b.title, strip_terms, opts.strip_parentheses),
                opts.name_display,
            ),
            "start": _fmt_hm(b.start, tz),
            "end": _fmt_hm(b.end, tz) if b.end else "",
            "active": is_active(b, now),
        }
        # Privacy: only include userID / email when the option is enabled, so
        # they are never even sent to the browser otherwise.
        if opts.show_email and b.organiser:
            row["email"] = b.organiser
        if opts.show_user_id:
            uid = email_local_part(b.organiser)
            if uid:
                row["user_id"] = uid
        rows.append(row)
    d["bookings"] = rows
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
              white-space: nowrap; overflow: hidden; flex: 1 1 auto; }
.panel-status { font-size: 1.5vw; font-weight: 800; letter-spacing: 0.05em;
                white-space: nowrap; opacity: 0.95; flex: 0 0 auto; }
.panel-room { font-size: 1.0vw; font-weight: 700; color: rgba(255,255,255,0.85);
              margin-top: 0.15vw; letter-spacing: 0.02em; }

/* Booking list. .bookings clips; .bookings-inner is what scrolls vertically. */
.bookings { margin-top: 0.7vw; overflow: hidden; flex: 1 1 auto; min-height: 0; }
.bookings-inner { display: flex; flex-direction: column; gap: 0.35vw; }
.brow { display: flex; align-items: baseline; gap: 0.8vw;
        background: rgba(0,0,0,0.18); border-radius: 0.4vw;
        padding: 0.3vw 0.7vw; font-size: 1.12vw; }
.brow.now { background: rgba(255,255,255,0.26); font-weight: 800; }
.btime { font-variant-numeric: tabular-nums; white-space: nowrap; flex: 0 0 auto; }
.bname { overflow: hidden; white-space: nowrap; flex: 1 1 auto; }
.bmeta { color: rgba(255,255,255,0.72); font-weight: 600; }
/* The inner span is translated by JS when its text overflows the tile. */
.scroller { display: inline-block; will-change: transform; }

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
  h += '<div class="panel-name"><span class="scroller">' + esc(inst.name) + '</span></div>';
  h += '<div class="panel-status">' + (STATUS_WORD[st] || '') + '</div>';
  h += '</div>';
  if (inst.room) h += '<div class="panel-room">' + esc(inst.room) + '</div>';

  if (st === 'down') {
    var inc = (inst.incidents && inst.incidents.length) ? inst.incidents[0] : null;
    h += '<div class="down-reason">' + (inc ? esc(inc.title) : 'Unavailable') + '</div>';
    if (inc) h += '<div class="down-dates">until ' + esc(inc.end) + '</div>';
  } else if (MODE === 'status-only') {
    h += '<div class="status-big">' + (st === 'inuse' ? 'In use' : st === 'nodata' ? 'No data' : 'Available') + '</div>';
  } else {
    h += '<div class="bookings"><div class="bookings-inner">';
    if (inst.error) {
      h += '<div class="note-line">calendar unavailable</div>';
    } else if (!inst.bookings || !inst.bookings.length) {
      h += '<div class="note-line">No bookings today</div>';
    } else {
      for (var i = 0; i < inst.bookings.length; i++) {
        var b = inst.bookings[i];
        var meta = [];
        if (b.user_id) meta.push(esc(b.user_id));
        if (b.email) meta.push(esc(b.email));
        var metaHTML = meta.length ? ' <span class="bmeta">' + meta.join(' &middot; ') + '</span>' : '';
        h += '<div class="brow' + (b.active ? ' now' : '') + '">';
        h += '<span class="btime">' + esc(b.start) + '-' + esc(b.end) + '</span>';
        h += '<span class="bname"><span class="scroller">' + esc(b.name) + metaHTML + '</span></span>';
        h += '</div>';
      }
    }
    h += '</div></div>';
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
  requestAnimationFrame(applyScrollers);
}

// Animate any name that is wider than its tile (horizontal), and any booking
// list that is taller than its tile (vertical). Runs after each draw.
function applyScrollers() {
  var names = document.querySelectorAll('.panel-name .scroller, .bname .scroller');
  for (var i = 0; i < names.length; i++) {
    var s = names[i];
    var over = s.scrollWidth - s.parentElement.clientWidth;
    if (over > 4) {
      var dur = Math.max(5000, over * 55);
      s.animate([
        { transform: 'translateX(0)' },
        { transform: 'translateX(0)', offset: 0.12 },
        { transform: 'translateX(-' + over + 'px)', offset: 0.50 },
        { transform: 'translateX(-' + over + 'px)', offset: 0.62 },
        { transform: 'translateX(0)', offset: 1 }
      ], { duration: dur, iterations: Infinity });
    }
  }
  var lists = document.querySelectorAll('.bookings');
  for (var j = 0; j < lists.length; j++) {
    var box = lists[j];
    var inner = box.querySelector('.bookings-inner');
    if (!inner) continue;
    var overY = inner.scrollHeight - box.clientHeight;
    if (overY > 4) {
      var durY = Math.max(6000, overY * 110);
      inner.animate([
        { transform: 'translateY(0)' },
        { transform: 'translateY(0)', offset: 0.10 },
        { transform: 'translateY(-' + overY + 'px)', offset: 0.50 },
        { transform: 'translateY(-' + overY + 'px)', offset: 0.60 },
        { transform: 'translateY(0)', offset: 1 }
      ], { duration: durY, iterations: Infinity });
    }
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
  // ticker_only entries have no tile; they only feed the incident ticker.
  var tiles = data.filter(function (d) { return !d.ticker_only; });
  pages = [];
  for (var i = 0; i < tiles.length; i += PER_PAGE) pages.push(tiles.slice(i, i + PER_PAGE));
  if (curPage >= pages.length) curPage = 0;
  drawPage();
  buildTicker(data);
}

// Self-adjusting rotation timer so a changed rotate_seconds takes effect live.
var rotateTimer = null;
function scheduleRotate() {
  clearTimeout(rotateTimer);
  rotateTimer = setTimeout(function () {
    if (pages.length > 1) {
      curPage = (curPage + 1) % pages.length;
      drawPage();
    }
    scheduleRotate();
  }, ROTATE_MS);
}

// Apply config that can change at runtime (title, mode, pagination, timers)
// without needing a full page reload.
function applyMeta(m) {
  if (!m) return;
  if (m.title != null) document.querySelector('.brand .b1').textContent = m.title;
  if (m.subtitle != null) document.querySelector('.brand .b2').textContent = m.subtitle;
  if (m.mode) MODE = m.mode;
  if (m.per_page) PER_PAGE = m.per_page;
  if (m.refresh_seconds) REFRESH_MS = m.refresh_seconds * 1000;
  var newRotate = (m.rotate_seconds || 20) * 1000;
  if (newRotate !== ROTATE_MS) { ROTATE_MS = newRotate; scheduleRotate(); }
}

var refreshTimer = null;
function scheduleLoad() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(load, REFRESH_MS);
}
function load() {
  // Cache-bust so the kiosk browser never serves a stale board.
  fetch('/api/status?t=' + Date.now(), { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) { applyMeta(d.meta); render(d.instruments); }
      scheduleLoad();
    })
    .catch(function () { scheduleLoad(); });
}
scheduleRotate();
load();
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


@app.after_request
def _no_cache(resp):
    """Stop the board's browser caching API responses, so edits show up at once."""
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/status")
def api_status():
    cfg = app.config["BILLBOARD"]
    return jsonify({
        "ok": True,
        # meta lets the board apply title/mode/pagination changes live, without
        # needing a full page reload.
        "meta": {
            "title": cfg.title,
            "subtitle": cfg.subtitle,
            "mode": cfg.mode,
            "per_page": cfg.per_page,
            "rotate_seconds": cfg.rotate_seconds,
            "refresh_seconds": cfg.refresh_seconds,
        },
        "instruments": fetch_all(cfg),
    })


@app.route("/config")
def config_builder():
    """Serve the standalone config-builder form (also openable as a file)."""
    path = Path(__file__).parent / "config_builder.html"
    return path.read_text(encoding="utf-8")


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """GET returns the current config JSON; POST saves a new config and applies it live."""
    save_path = app.config.get("CONFIG_PATH")

    if request.method == "GET":
        src = save_path if (save_path and save_path.exists()) else _EXAMPLE_CONFIG
        return app.response_class(src.read_text(encoding="utf-8"), mimetype="application/json")

    # POST: validate, write to disk, and hot-swap the live config (no restart).
    if not ALLOW_WRITE:
        return jsonify({"ok": False, "error": "Server is in read-only mode"}), 403
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Request body must be a JSON object"}), 400
    try:
        cfg = parse_billboard_config(data)
    except BillboardConfigError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    save_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    app.config["BILLBOARD"] = cfg  # board picks this up on its next refresh
    return jsonify({
        "ok": True,
        "saved_to": str(save_path),
        "instruments": len(cfg.instruments),
    })


def main():
    try:
        cfg, save_path = load_config()
    except BillboardConfigError as exc:
        print("  Config error: " + str(exc))
        sys.exit(1)
    app.config["BILLBOARD"] = cfg
    app.config["CONFIG_PATH"] = save_path

    print("")
    print("  Lab Flightboard - Instrument Status Billboard")
    print("  ---------------------------------------------")
    print("  Title       : " + cfg.title)
    print("  Mode        : " + cfg.mode)
    print("  Instruments : " + str(len(enabled_instruments(cfg))))
    print("  Per screen  : " + str(cfg.per_page) + "  (rotate every " + str(cfg.rotate_seconds) + "s if more)")
    print("  Refresh     : every " + str(cfg.refresh_seconds) + "s")
    print("  Config file : " + str(save_path) + ("" if ALLOW_WRITE else "  (read-only)"))
    print("")
    print("  Board   : http://localhost:" + str(HTTP_PORT) + "   (press F11 for full screen)")
    print("  Editor  : http://localhost:" + str(HTTP_PORT) + "/config   (edit + apply live)")
    print("")
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False)


if __name__ == "__main__":
    main()
