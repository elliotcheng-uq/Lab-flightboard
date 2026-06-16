#!/usr/bin/env python3
"""Minimal dev server for testing the iCal parser in a browser.

Usage:
    python examples/dev_server.py
    # then open http://localhost:5050
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, request, jsonify, render_template_string
from lab_flightboard import (
    fetch_ical_from_url,
    parse_ical_bytes,
    parse_events_from_calendar,
    CalendarFetchError,
    CalendarParseError,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def _booking_to_dict(b) -> dict:
    return {
        "uid": b.uid,
        "title": b.title,
        "start": b.start.isoformat() if b.start else None,
        "end": b.end.isoformat() if b.end else None,
        "duration_minutes": b.duration_minutes,
        "status": b.status,
        "location": b.location,
        "description": b.description,
        "organiser": b.organiser,
        "categories": b.categories,
        "is_cancelled": b.is_cancelled,
        "is_recurring": b.is_recurring,
        "created": b.created.isoformat() if b.created else None,
        "last_modified": b.last_modified.isoformat() if b.last_modified else None,
        "sequence": b.sequence,
        "vendor_fields": b.vendor_fields,
        "raw_properties": b.raw_properties,
    }


def _parse_ics_bytes(data: bytes, equipment_id: str, equipment_name: str, source_url: str = "") -> dict:
    cal = parse_ical_bytes(data)
    bookings = parse_events_from_calendar(cal, equipment_id, equipment_name,
                                          source_calendar_url=source_url or None)
    # Collect unique field names
    all_fields: set[str] = set()
    x_fields: set[str] = set()
    has_rrule = False
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        for key in component.keys():
            k = str(key)
            all_fields.add(k)
            if k.upper().startswith("X-"):
                x_fields.add(k)
        if component.get("RRULE") is not None:
            has_rrule = True

    return {
        "success": True,
        "calendar": {
            "name": str(cal.get("X-WR-CALNAME") or ""),
            "timezone": str(cal.get("X-WR-TIMEZONE") or ""),
            "prodid": str(cal.get("PRODID") or ""),
            "event_count": len(bookings),
            "has_recurring": has_rrule,
            "standard_fields": sorted(f for f in all_fields if not f.upper().startswith("X-")),
            "x_fields": sorted(x_fields),
        },
        "bookings": [_booking_to_dict(b) for b in
                     sorted(bookings, key=lambda b: b.start)],
    }


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/parse-url")
def parse_url():
    body = request.get_json(force=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"success": False, "error": "url is required"}), 400
    equipment_id = body.get("equipment_id") or "eq-01"
    equipment_name = body.get("equipment_name") or "Equipment"
    try:
        data = fetch_ical_from_url(url)
        return jsonify(_parse_ics_bytes(data, equipment_id, equipment_name, url))
    except (CalendarFetchError, CalendarParseError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": f"Unexpected error: {exc}"}), 500


@app.post("/api/parse-file")
def parse_file():
    f = request.files.get("file")
    if not f:
        return jsonify({"success": False, "error": "No file uploaded"}), 400
    equipment_id = request.form.get("equipment_id") or "eq-01"
    equipment_name = request.form.get("equipment_name") or "Equipment"
    try:
        data = f.read()
        return jsonify(_parse_ics_bytes(data, equipment_id, equipment_name))
    except (CalendarParseError, Exception) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lab Flightboard — iCal Tester</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    background: #0f1117;
    color: #e2e8f0;
    min-height: 100vh;
  }

  header {
    background: #1a1d2e;
    border-bottom: 1px solid #2d3148;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  header h1 { font-size: 18px; font-weight: 600; letter-spacing: 0.03em; color: #f0f4ff; }
  header .badge {
    background: #2563eb;
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 4px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .layout { display: grid; grid-template-columns: 360px 1fr; min-height: calc(100vh - 53px); }

  /* ---- Sidebar ---- */
  .sidebar {
    background: #141622;
    border-right: 1px solid #2d3148;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .tabs { display: flex; border: 1px solid #2d3148; border-radius: 6px; overflow: hidden; }
  .tab-btn {
    flex: 1; padding: 8px; background: none; border: none; color: #94a3b8;
    cursor: pointer; font-size: 13px; font-weight: 500; transition: all .15s;
  }
  .tab-btn.active { background: #2563eb; color: #fff; }
  .tab-btn:not(.active):hover { background: #1e2340; color: #e2e8f0; }

  .tab-panel { display: none; flex-direction: column; gap: 12px; }
  .tab-panel.active { display: flex; }

  label { font-size: 12px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.06em; }
  input[type=text], input[type=file] {
    width: 100%; padding: 8px 10px; background: #0f1117; border: 1px solid #2d3148;
    border-radius: 6px; color: #e2e8f0; font-size: 13px; margin-top: 4px;
    outline: none; transition: border-color .15s;
  }
  input[type=text]:focus { border-color: #2563eb; }
  input[type=file] { padding: 6px 10px; cursor: pointer; }

  .field-row { display: flex; flex-direction: column; gap: 4px; }

  .eq-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }

  .btn-parse {
    width: 100%; padding: 10px; background: #2563eb; border: none; border-radius: 6px;
    color: #fff; font-size: 14px; font-weight: 600; cursor: pointer; transition: background .15s;
    margin-top: 4px;
  }
  .btn-parse:hover { background: #1d4ed8; }
  .btn-parse:disabled { background: #1e3a6e; color: #6b7280; cursor: not-allowed; }

  .hint { font-size: 11px; color: #64748b; margin-top: 6px; line-height: 1.5; }

  /* ---- Main panel ---- */
  .main { padding: 24px; overflow-y: auto; }

  .empty-state {
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: #475569;
  }
  .empty-state svg { opacity: 0.3; }
  .empty-state p { font-size: 15px; }

  /* ---- Calendar info bar ---- */
  .cal-info {
    display: flex; flex-wrap: wrap; gap: 12px;
    background: #1a1d2e; border: 1px solid #2d3148; border-radius: 8px;
    padding: 14px 18px; margin-bottom: 20px; align-items: center;
  }
  .cal-chip {
    display: flex; flex-direction: column; gap: 2px;
  }
  .cal-chip .cl { font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; }
  .cal-chip .cv { font-size: 13px; color: #e2e8f0; }
  .cal-chip .cv.pill {
    background: #0f3460; color: #60a5fa; font-size: 11px; font-weight: 700;
    padding: 2px 8px; border-radius: 12px; display: inline-block;
  }

  .x-fields-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .x-tag {
    background: #1e2a45; color: #93c5fd; font-size: 11px; font-weight: 600;
    padding: 2px 8px; border-radius: 4px; font-family: monospace;
  }

  /* ---- Booking cards ---- */
  .booking-grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }

  .booking-card {
    background: #141622; border: 1px solid #2d3148; border-radius: 8px;
    padding: 14px 16px; display: flex; flex-direction: column; gap: 8px;
    position: relative;
  }
  .booking-card.cancelled { opacity: .5; border-color: #4b1818; }
  .booking-card.current { border-color: #16a34a; }

  .card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
  .card-title { font-size: 14px; font-weight: 600; color: #f0f4ff; line-height: 1.3; }
  .card-badges { display: flex; gap: 4px; flex-wrap: wrap; flex-shrink: 0; }

  .badge-status {
    font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px;
    text-transform: uppercase; letter-spacing: .05em;
  }
  .badge-status.confirmed { background: #14532d; color: #4ade80; }
  .badge-status.cancelled { background: #4b1818; color: #f87171; }
  .badge-status.tentative { background: #422006; color: #fb923c; }
  .badge-status.other { background: #1e2340; color: #94a3b8; }
  .badge-recurring { background: #1e1b4b; color: #a78bfa; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; text-transform: uppercase; letter-spacing: .05em; }

  .card-time { font-size: 12px; color: #64748b; }
  .card-time .dt { color: #94a3b8; }
  .card-time .dur { color: #475569; }

  .card-meta { display: flex; flex-direction: column; gap: 3px; }
  .meta-row { font-size: 12px; color: #64748b; }
  .meta-row span { color: #94a3b8; }

  .cats { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 2px; }
  .cat { background: #1e293b; color: #7dd3fc; font-size: 11px; padding: 1px 7px; border-radius: 3px; }

  .vendor-toggle {
    background: none; border: 1px solid #2d3148; border-radius: 4px;
    color: #64748b; font-size: 11px; cursor: pointer; padding: 3px 8px;
    text-align: left; width: 100%; transition: all .15s;
  }
  .vendor-toggle:hover { border-color: #4b5563; color: #94a3b8; }

  .vendor-table {
    display: none; font-size: 11px; font-family: monospace;
    border: 1px solid #1e2340; border-radius: 4px; overflow: hidden; margin-top: 2px;
  }
  .vendor-table.open { display: table; width: 100%; border-collapse: collapse; }
  .vendor-table td { padding: 4px 8px; border-bottom: 1px solid #1e2340; vertical-align: top; }
  .vendor-table tr:last-child td { border-bottom: none; }
  .vendor-table td:first-child { color: #60a5fa; white-space: nowrap; width: 40%; }
  .vendor-table td:last-child { color: #cbd5e1; word-break: break-all; }
  .vendor-table tr:nth-child(even) td { background: #0f1117; }

  .raw-toggle {
    background: none; border: none; color: #475569; font-size: 11px; cursor: pointer;
    padding: 2px 0; text-align: left; transition: color .15s;
  }
  .raw-toggle:hover { color: #64748b; }

  .raw-block {
    display: none; background: #0a0c15; border: 1px solid #1e2340; border-radius: 4px;
    padding: 8px; font-family: monospace; font-size: 10px; color: #64748b;
    max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
  }
  .raw-block.open { display: block; }

  /* ---- Error ---- */
  .error-box {
    background: #2d0a0a; border: 1px solid #7f1d1d; border-radius: 8px;
    padding: 14px 18px; color: #fca5a5; font-size: 13px;
  }
  .error-box strong { display: block; margin-bottom: 4px; color: #f87171; }

  /* ---- Spinner ---- */
  .spinner {
    width: 20px; height: 20px; border: 2px solid #2d3148;
    border-top-color: #2563eb; border-radius: 50%;
    animation: spin .7s linear infinite; display: none;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner.active { display: inline-block; }

  .parse-row { display: flex; align-items: center; gap: 10px; }
  .parse-row .btn-parse { flex: 1; margin-top: 0; }

  .section-title { font-size: 13px; font-weight: 600; color: #64748b; margin-bottom: 12px; text-transform: uppercase; letter-spacing: .06em; }
</style>
</head>
<body>

<header>
  <h1>Lab Flightboard</h1>
  <span class="badge">iCal Tester</span>
</header>

<div class="layout">

  <!-- ── Sidebar ── -->
  <aside class="sidebar">
    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('url')">URL</button>
      <button class="tab-btn" onclick="switchTab('file')">Upload ICS</button>
    </div>

    <!-- URL tab -->
    <div id="tab-url" class="tab-panel active">
      <div class="field-row">
        <label>Calendar URL</label>
        <input type="text" id="cal-url" placeholder="https://example.com/calendar.ics"
               onkeydown="if(event.key==='Enter') parseUrl()">
      </div>
      <div class="eq-row">
        <div class="field-row">
          <label>Equipment ID</label>
          <input type="text" id="eq-id-url" value="eq-01">
        </div>
        <div class="field-row">
          <label>Display Name</label>
          <input type="text" id="eq-name-url" value="Equipment 01">
        </div>
      </div>
      <div class="parse-row">
        <button class="btn-parse" onclick="parseUrl()" id="btn-url">Parse Calendar</button>
        <div class="spinner" id="spin-url"></div>
      </div>
      <p class="hint">The URL is never shown in logs. Only the domain is used for safe display.</p>
    </div>

    <!-- File tab -->
    <div id="tab-file" class="tab-panel">
      <div class="field-row">
        <label>ICS File</label>
        <input type="file" id="cal-file" accept=".ics,.ical">
      </div>
      <div class="eq-row">
        <div class="field-row">
          <label>Equipment ID</label>
          <input type="text" id="eq-id-file" value="eq-01">
        </div>
        <div class="field-row">
          <label>Display Name</label>
          <input type="text" id="eq-name-file" value="Equipment 01">
        </div>
      </div>
      <div class="parse-row">
        <button class="btn-parse" onclick="parseFile()" id="btn-file">Parse File</button>
        <div class="spinner" id="spin-file"></div>
      </div>
    </div>
  </aside>

  <!-- ── Main panel ── -->
  <main class="main" id="main">
    <div class="empty-state">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/>
        <line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
      </svg>
      <p>Paste a calendar URL or upload an ICS file to inspect it.</p>
    </div>
  </main>

</div>

<script>
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach((b, i) =>
    b.classList.toggle('active', ['url','file'][i] === name));
  document.querySelectorAll('.tab-panel').forEach(p =>
    p.classList.toggle('active', p.id === 'tab-' + name));
}

function setLoading(id, on) {
  document.getElementById('btn-' + id).disabled = on;
  document.getElementById('spin-' + id).classList.toggle('active', on);
}

async function parseUrl() {
  const url = document.getElementById('cal-url').value.trim();
  if (!url) return;
  setLoading('url', true);
  try {
    const r = await fetch('/api/parse-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        url,
        equipment_id: document.getElementById('eq-id-url').value.trim() || 'eq-01',
        equipment_name: document.getElementById('eq-name-url').value.trim() || 'Equipment',
      })
    });
    render(await r.json());
  } catch (e) {
    renderError('Network error: ' + e.message);
  } finally {
    setLoading('url', false);
  }
}

async function parseFile() {
  const file = document.getElementById('cal-file').files[0];
  if (!file) return;
  setLoading('file', true);
  const fd = new FormData();
  fd.append('file', file);
  fd.append('equipment_id', document.getElementById('eq-id-file').value.trim() || 'eq-01');
  fd.append('equipment_name', document.getElementById('eq-name-file').value.trim() || 'Equipment');
  try {
    const r = await fetch('/api/parse-file', {method:'POST', body:fd});
    render(await r.json());
  } catch (e) {
    renderError('Network error: ' + e.message);
  } finally {
    setLoading('file', false);
  }
}

function render(data) {
  const main = document.getElementById('main');
  if (!data.success) { renderError(data.error); return; }
  const {calendar: cal, bookings} = data;
  const now = new Date();

  let html = '';

  // ── Calendar info bar ──
  html += `<div class="cal-info">`;
  html += chip('Calendar', cal.name || '<unnamed>');
  html += chip('Timezone', cal.timezone || '—');
  html += chip('Events', `<span class="pill">${cal.event_count}</span>`);
  html += chip('Recurring', cal.has_recurring ? 'Yes' : 'No');
  if (cal.prodid) html += chip('PRODID', cal.prodid);
  html += `</div>`;

  // Standard fields row
  if (cal.standard_fields.length) {
    html += `<div style="margin-bottom:8px;"><span class="section-title">Standard fields &nbsp;</span>`;
    html += cal.standard_fields.map(f => `<span class="cat">${esc(f)}</span>`).join(' ');
    html += `</div>`;
  }

  // X-* fields row
  if (cal.x_fields.length) {
    html += `<div style="margin-bottom:16px;"><span class="section-title">X-* fields &nbsp;</span>`;
    html += cal.x_fields.map(f => `<span class="x-tag">${esc(f)}</span>`).join(' ');
    html += `</div>`;
  }

  // ── Booking cards ──
  html += `<div class="section-title">${bookings.length} Booking${bookings.length !== 1 ? 's' : ''}</div>`;
  html += `<div class="booking-grid">`;

  bookings.forEach((b, idx) => {
    const start = b.start ? new Date(b.start) : null;
    const end = b.end ? new Date(b.end) : null;
    const isCurrent = start && end && start <= now && now < end;
    const cancelled = b.is_cancelled;

    let cardClass = 'booking-card';
    if (cancelled) cardClass += ' cancelled';
    if (isCurrent) cardClass += ' current';

    html += `<div class="${cardClass}">`;

    // Header: title + badges
    html += `<div class="card-header"><div class="card-title">${esc(b.title)}</div>`;
    html += `<div class="card-badges">`;
    if (b.status) {
      const sc = (b.status || '').toLowerCase();
      const cls = sc === 'confirmed' ? 'confirmed' : sc === 'cancelled' ? 'cancelled' : sc === 'tentative' ? 'tentative' : 'other';
      html += `<span class="badge-status ${cls}">${esc(b.status)}</span>`;
    }
    if (isCurrent) html += `<span class="badge-status confirmed">NOW</span>`;
    if (b.is_recurring) html += `<span class="badge-recurring">↻ recurring</span>`;
    html += `</div></div>`;

    // Times
    if (start) {
      const startStr = fmtDt(start);
      const endStr = end ? fmtDt(end) : null;
      const dur = b.duration_minutes != null ? fmtDur(b.duration_minutes) : null;
      html += `<div class="card-time">`;
      html += `<span class="dt">${startStr}</span>`;
      if (endStr) html += ` → <span class="dt">${endStr}</span>`;
      if (dur) html += ` <span class="dur">(${dur})</span>`;
      html += `</div>`;
    }

    // Meta
    html += `<div class="card-meta">`;
    if (b.location) html += `<div class="meta-row">📍 <span>${esc(b.location)}</span></div>`;
    if (b.organiser) html += `<div class="meta-row">👤 <span>${esc(b.organiser)}</span></div>`;
    if (b.description) html += `<div class="meta-row">📝 <span>${esc(b.description.substring(0,120))}${b.description.length>120?'…':''}</span></div>`;
    html += `</div>`;

    if (b.categories.length) {
      html += `<div class="cats">` + b.categories.map(c => `<span class="cat">${esc(c)}</span>`).join('') + `</div>`;
    }

    // Vendor fields
    if (Object.keys(b.vendor_fields).length) {
      const vid = `vendor-${idx}`;
      html += `<button class="vendor-toggle" onclick="toggleVendor('${vid}')">▸ X-* vendor fields (${Object.keys(b.vendor_fields).length})</button>`;
      html += `<table class="vendor-table" id="${vid}">`;
      for (const [k, v] of Object.entries(b.vendor_fields)) {
        html += `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`;
      }
      html += `</table>`;
    }

    // Raw properties toggle
    const rid = `raw-${idx}`;
    const rawText = Object.entries(b.raw_properties).map(([k,v])=>`${k}: ${v}`).join('\n');
    html += `<button class="raw-toggle" onclick="toggleRaw('${rid}')">▸ raw properties</button>`;
    html += `<pre class="raw-block" id="${rid}">${esc(rawText)}</pre>`;

    html += `</div>`;
  });

  html += `</div>`;
  main.innerHTML = html;
}

function renderError(msg) {
  document.getElementById('main').innerHTML =
    `<div class="error-box"><strong>Error</strong>${esc(msg)}</div>`;
}

function chip(label, value) {
  return `<div class="cal-chip"><span class="cl">${label}</span><span class="cv">${value}</span></div>`;
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtDt(d) {
  return d.toLocaleString(undefined, {year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
}

function fmtDur(mins) {
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins/60), m = mins%60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function toggleVendor(id) {
  const el = document.getElementById(id);
  const btn = el.previousElementSibling;
  const open = el.classList.toggle('open');
  btn.textContent = (open ? '▾' : '▸') + btn.textContent.slice(1);
}

function toggleRaw(id) {
  const el = document.getElementById(id);
  const btn = el.previousElementSibling;
  const open = el.classList.toggle('open');
  btn.textContent = (open ? '▾' : '▸') + btn.textContent.slice(1);
}
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    print("Lab Flightboard dev server running at http://localhost:5050")
    app.run(host="127.0.0.1", port=5050, debug=True)
