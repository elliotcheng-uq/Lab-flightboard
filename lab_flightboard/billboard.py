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
