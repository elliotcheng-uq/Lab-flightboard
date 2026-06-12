import logging
from datetime import date, datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
import recurring_ical_events
from icalendar import Calendar

from .exceptions import CalendarFetchError, CalendarParseError
from .models import CalendarBooking, EquipmentCalendar

logger = logging.getLogger(__name__)

_USER_AGENT = "LabFlightboard/0.1"
_ACCEPT_HEADER = "text/calendar,*/*"


# ---------------------------------------------------------------------------
# URL safety helper — keep tokens out of logs
# ---------------------------------------------------------------------------

def _safe_url(url: str) -> str:
    """Return a log-safe version of a URL (scheme + host only, path/query omitted)."""
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}/..."
    except Exception:
        return "<URL>"


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _normalise_url(url: str) -> str:
    """Convert webcal:// and webcals:// to their https equivalents."""
    lower = url.lower()
    if lower.startswith("webcals://"):
        return "https://" + url[10:]
    if lower.startswith("webcal://"):
        return "https://" + url[9:]
    return url


def fetch_ical_from_url(url: str, timeout: int = 20) -> bytes:
    """Download raw ICS data from a URL."""
    url = _normalise_url(url)
    logger.debug("Fetching calendar from %s", _safe_url(url))
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT, "Accept": _ACCEPT_HEADER},
        )
        response.raise_for_status()
        return response.content
    except requests.exceptions.Timeout as exc:
        raise CalendarFetchError(
            f"Timed out fetching calendar from {_safe_url(url)}"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise CalendarFetchError(
            f"Failed to fetch calendar from {_safe_url(url)}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_ical_bytes(data: bytes) -> Calendar:
    """Parse raw ICS bytes into a Calendar object."""
    try:
        return Calendar.from_ical(data)
    except Exception as exc:
        raise CalendarParseError(f"Failed to parse iCal data: {exc}") from exc


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _to_datetime(value) -> Optional[datetime]:
    """Normalise a DTSTART/DTEND value to a datetime, converting all-day dates to UTC midnight."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return None


def _get_str(component, key: str) -> Optional[str]:
    val = component.get(key)
    return str(val) if val is not None else None


def _get_categories(component) -> list[str]:
    raw = component.get("CATEGORIES")
    if raw is None:
        return []
    try:
        return [str(c) for c in raw.cats]
    except AttributeError:
        return [str(raw)]


# ---------------------------------------------------------------------------
# VEVENT → CalendarBooking
# ---------------------------------------------------------------------------

def component_to_booking(
    component,
    equipment_id: str,
    equipment_name: str,
    source_calendar_url: Optional[str] = None,
) -> CalendarBooking:
    """Convert one VEVENT component into a normalised CalendarBooking."""
    uid = _get_str(component, "UID") or ""

    dtstart_raw = component.get("DTSTART")
    if dtstart_raw is None:
        raise CalendarParseError(f"VEVENT {uid!r} is missing DTSTART")
    start = _to_datetime(dtstart_raw.dt)
    if start is None:
        raise CalendarParseError(f"VEVENT {uid!r}: could not interpret DTSTART value")

    dtend_raw = component.get("DTEND")
    duration_raw = component.get("DURATION")
    if dtend_raw is not None:
        end = _to_datetime(dtend_raw.dt)
    elif duration_raw is not None:
        end = start + duration_raw.dt
    else:
        end = None

    status = _get_str(component, "STATUS")
    is_cancelled = (status or "").upper() == "CANCELLED"

    organiser_raw = component.get("ORGANIZER")
    organiser: Optional[str] = None
    if organiser_raw is not None:
        organiser = str(organiser_raw)
        if organiser.lower().startswith("mailto:"):
            organiser = organiser[7:]

    created_raw = component.get("CREATED")
    last_modified_raw = component.get("LAST-MODIFIED")
    sequence_raw = component.get("SEQUENCE")

    is_recurring = (
        component.get("RRULE") is not None
        or component.get("RECURRENCE-ID") is not None
    )

    vendor_fields: dict[str, str] = {}
    raw_properties: dict[str, str] = {}
    for key, val in component.items():
        k = str(key)
        raw_properties[k] = str(val)
        if k.upper().startswith("X-"):
            vendor_fields[k] = str(val)

    return CalendarBooking(
        uid=uid,
        equipment_id=equipment_id,
        equipment_name=equipment_name,
        title=_get_str(component, "SUMMARY") or "Untitled booking",
        start=start,
        end=end,
        status=status,
        location=_get_str(component, "LOCATION"),
        description=_get_str(component, "DESCRIPTION"),
        organiser=organiser,
        categories=_get_categories(component),
        source_calendar_url=source_calendar_url,
        is_cancelled=is_cancelled,
        is_recurring=is_recurring,
        created=_to_datetime(created_raw.dt) if created_raw else None,
        last_modified=_to_datetime(last_modified_raw.dt) if last_modified_raw else None,
        sequence=int(sequence_raw) if sequence_raw is not None else None,
        vendor_fields=vendor_fields,
        raw_properties=raw_properties,
    )


# ---------------------------------------------------------------------------
# Calendar-level parsing
# ---------------------------------------------------------------------------

def parse_events_from_calendar(
    calendar: Calendar,
    equipment_id: str,
    equipment_name: str,
    source_calendar_url: Optional[str] = None,
) -> list[CalendarBooking]:
    """Parse VEVENT components from a calendar without expanding recurrences."""
    bookings: list[CalendarBooking] = []
    for component in calendar.walk():
        if component.name != "VEVENT":
            continue
        try:
            bookings.append(
                component_to_booking(component, equipment_id, equipment_name, source_calendar_url)
            )
        except CalendarParseError as exc:
            logger.warning("Skipping event: %s", exc)
    return bookings


def parse_occurrences_from_url(
    url: str,
    equipment_id: str,
    equipment_name: str,
    start: datetime,
    end: datetime,
) -> list[CalendarBooking]:
    """Fetch a calendar and return all event occurrences (including expanded recurrences) between start and end."""
    data = fetch_ical_from_url(url)
    cal = parse_ical_bytes(data)
    raw_events = recurring_ical_events.of(cal).between(start, end)
    bookings: list[CalendarBooking] = []
    for component in raw_events:
        try:
            bookings.append(component_to_booking(component, equipment_id, equipment_name, url))
        except CalendarParseError as exc:
            logger.warning("Skipping occurrence: %s", exc)
    bookings.sort(key=lambda b: b.start if b.start.tzinfo else b.start.replace(tzinfo=timezone.utc))
    return bookings


def parse_all_equipment(
    equipment_list: list[EquipmentCalendar],
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    expand_recurring: bool = False,
) -> tuple[list[CalendarBooking], list[dict]]:
    """
    Parse bookings for all enabled equipment entries.

    Returns (bookings, errors).  Errors are dicts with keys 'equipment_id' and 'error'.
    The function continues when a single equipment fails so the others are not affected.
    """
    all_bookings: list[CalendarBooking] = []
    errors: list[dict] = []

    for eq in equipment_list:
        if not eq.enabled:
            continue
        try:
            if expand_recurring and start and end:
                bookings = parse_occurrences_from_url(
                    eq.calendar_url, eq.equipment_id, eq.equipment_name, start, end
                )
            else:
                data = fetch_ical_from_url(eq.calendar_url)
                cal = parse_ical_bytes(data)
                bookings = parse_events_from_calendar(
                    cal, eq.equipment_id, eq.equipment_name, eq.calendar_url
                )
            all_bookings.extend(bookings)
        except Exception as exc:
            logger.error(
                "Failed to parse calendar for equipment %r (%s): %s",
                eq.equipment_id,
                _safe_url(eq.calendar_url),
                exc,
            )
            errors.append({"equipment_id": eq.equipment_id, "error": str(exc)})

    all_bookings.sort(
        key=lambda b: b.start if b.start.tzinfo else b.start.replace(tzinfo=timezone.utc)
    )
    return all_bookings, errors
