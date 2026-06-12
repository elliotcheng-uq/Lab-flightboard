"""Status derivation for the airport-style instrument billboard.

This module turns parsed CalendarBooking objects into a per-instrument view
with a live status (free / inuse / down). It is deliberately network-free so it
can be unit tested with fake bookings; the example app supplies the bookings.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from .models import CalendarBooking

VALID_MODES = ("full", "status-only")

# Status values used on the board tiles
STATUS_FREE = "free"
STATUS_INUSE = "inuse"
STATUS_DOWN = "down"
STATUS_NODATA = "nodata"


@dataclass
class InstrumentView:
    """Everything the board needs to render one instrument tile."""
    equipment_id: str
    equipment_name: str
    status: str  # free | inuse | down | nodata
    bookings: list[CalendarBooking] = field(default_factory=list)
    incidents: list[CalendarBooking] = field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Title cleaning
# ---------------------------------------------------------------------------

def clean_title(title: Optional[str], strip: Optional[str]) -> str:
    """Remove a repeated instrument name from a booking title.

    Many booking systems embed the instrument name in every SUMMARY, e.g.
    "A. Researcher (DEMO SEM)". Passing strip="DEMO SEM" leaves "A. Researcher".
    """
    s = title or ""
    if strip:
        s = s.replace("(" + strip + ")", " ")
        stripped = s.lstrip()
        if stripped.startswith(strip):
            s = stripped[len(strip):]
    s = " ".join(s.split())
    return s or "Booked"


def format_name(name: str, mode: str = "full") -> str:
    """Render a person's name as either the full name or initials.

    "Alice Researcher" -> "Alice Researcher"  (mode="full")
    "Alice Researcher" -> "A. R."             (mode="initials")
    """
    if mode == "initials":
        parts = [p for p in name.replace(".", " ").replace(",", " ").split() if p]
        if not parts:
            return name
        return ". ".join(p[0].upper() for p in parts) + "."
    return name


def email_local_part(email: Optional[str]) -> Optional[str]:
    """Derive a userID from an email address ("a.smith@x.edu" -> "a.smith")."""
    if not email:
        return None
    return email.split("@", 1)[0] if "@" in email else email


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _to_tz(dt: Optional[datetime], tz) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def is_active(booking: CalendarBooking, now: datetime) -> bool:
    """True if `now` falls within the booking's [start, end] span."""
    if booking.start is None:
        return False
    start = booking.start if booking.start.tzinfo else booking.start.replace(tzinfo=now.tzinfo)
    if booking.end is not None:
        end = booking.end if booking.end.tzinfo else booking.end.replace(tzinfo=now.tzinfo)
    else:
        end = start
    return start <= now <= end


def _hm_to_minutes(hm: str) -> int:
    try:
        h, m = hm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


def _minute_of_day(dt: datetime, tz) -> int:
    local = dt.astimezone(tz)
    return local.hour * 60 + local.minute


def overlaps_business(booking: CalendarBooking, tz, start_hm: str, end_hm: str) -> bool:
    """True if a booking overlaps the [start_hm, end_hm) window on its own day.

    Used for the "9 to 6" display option, which lists only bookings inside
    business hours. Status (free/inuse/down) is unaffected - it always reflects
    the real calendar.
    """
    if booking.start is None:
        return False
    start_min = _hm_to_minutes(start_hm)
    end_min = _hm_to_minutes(end_hm)
    bs = _minute_of_day(booking.start, tz)
    be = _minute_of_day(booking.end, tz) if booking.end else bs
    if be < bs:  # crosses midnight; clamp to end of day for this check
        be = 24 * 60
    return bs < end_min and be > start_min


# ---------------------------------------------------------------------------
# Incident classification & status
# ---------------------------------------------------------------------------

def classify_incident(
    booking: CalendarBooking,
    incident_categories: Sequence[str],
    incident_keywords: Sequence[str] = (),
) -> bool:
    """Decide whether an event from a booking feed is really an incident.

    An event counts as an incident if any of its CATEGORIES matches
    incident_categories, or any incident_keywords appears in its title.
    Matching is case-insensitive.
    """
    cats = {c.lower() for c in booking.categories}
    if cats & {c.lower() for c in incident_categories}:
        return True
    title = (booking.title or "").lower()
    return any(k.lower() in title for k in incident_keywords)


def derive_status(
    bookings: Sequence[CalendarBooking],
    incidents: Sequence[CalendarBooking],
    now: datetime,
) -> str:
    """Down beats in-use beats free. An active incident always wins."""
    if any(is_active(i, now) for i in incidents):
        return STATUS_DOWN
    if any(is_active(b, now) for b in bookings):
        return STATUS_INUSE
    return STATUS_FREE


# ---------------------------------------------------------------------------
# View builder (the testable core)
# ---------------------------------------------------------------------------

def build_instrument_view(
    equipment_id: str,
    equipment_name: str,
    booking_events: Sequence[CalendarBooking],
    incident_events: Sequence[CalendarBooking],
    now: datetime,
    tz,
    incident_categories: Sequence[str],
    incident_keywords: Sequence[str] = (),
    error: Optional[str] = None,
) -> InstrumentView:
    """Combine booking and incident feeds into a single instrument view.

    - booking_events: events from the instrument's booking feed (some may turn
      out to be incidents based on their categories/keywords).
    - incident_events: events from a dedicated incident feed (all treated as
      incidents).
    """
    if error is not None:
        return InstrumentView(equipment_id, equipment_name, STATUS_NODATA, error=error)

    bookings: list[CalendarBooking] = []
    incidents: list[CalendarBooking] = list(incident_events)
    for ev in booking_events:
        if classify_incident(ev, incident_categories, incident_keywords):
            incidents.append(ev)
        else:
            bookings.append(ev)

    status = derive_status(bookings, incidents, now)

    today = now.astimezone(tz).date()
    todays_bookings = sorted(
        [b for b in bookings if b.start and _to_tz(b.start, tz).date() == today],
        key=lambda b: b.start,
    )
    # Active or upcoming incidents (anything not yet ended)
    shown_incidents = sorted(
        [
            i for i in incidents
            if (i.end or i.start) and _to_tz(i.end or i.start, tz) >= now
        ],
        key=lambda i: i.start,
    )

    return InstrumentView(
        equipment_id=equipment_id,
        equipment_name=equipment_name,
        status=status,
        bookings=todays_bookings,
        incidents=shown_incidents,
        error=None,
    )
