"""Unit tests for the Lab Flightboard iCal parser.

All tests use inline ICS strings or the fixture file — no real HTTP requests are made.
"""
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from lab_flightboard.exceptions import CalendarParseError, CalendarFetchError
from lab_flightboard.ical_parser import (
    component_to_booking,
    parse_all_equipment,
    parse_events_from_calendar,
    parse_ical_bytes,
)
from lab_flightboard.models import EquipmentCalendar

FIXTURE = Path(__file__).parent / "fixtures" / "sample_calendar.ics"

EQ_ID = "eq-01"
EQ_NAME = "Equipment 01"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ics(*events: str) -> bytes:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Test//EN",
        *events,
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines).encode()


def vevent(**fields: str) -> str:
    body = "\r\n".join(f"{k}:{v}" for k, v in fields.items())
    return f"BEGIN:VEVENT\r\n{body}\r\nEND:VEVENT"


# ---------------------------------------------------------------------------
# 1. Basic single event with DTEND
# ---------------------------------------------------------------------------

def test_basic_event_with_dtend():
    ics = make_ics(vevent(
        UID="test-001@example.com",
        DTSTART="20260615T090000Z",
        DTEND="20260615T110000Z",
        SUMMARY="Test Event",
    ))
    cal = parse_ical_bytes(ics)
    bookings = parse_events_from_calendar(cal, EQ_ID, EQ_NAME)
    assert len(bookings) == 1
    b = bookings[0]
    assert b.uid == "test-001@example.com"
    assert b.title == "Test Event"
    assert b.equipment_id == EQ_ID
    assert b.start < b.end


# ---------------------------------------------------------------------------
# 2. Event with DTEND (explicit end datetime stored correctly)
# ---------------------------------------------------------------------------

def test_event_end_datetime_stored():
    ics = make_ics(vevent(
        UID="test-dtend@example.com",
        DTSTART="20260615T090000Z",
        DTEND="20260615T170000Z",
        SUMMARY="Full Day Research",
    ))
    cal = parse_ical_bytes(ics)
    bookings = parse_events_from_calendar(cal, EQ_ID, EQ_NAME)
    assert bookings[0].end is not None
    assert bookings[0].duration_minutes == 480.0


# ---------------------------------------------------------------------------
# 3. Event with DURATION instead of DTEND
# ---------------------------------------------------------------------------

def test_event_with_duration():
    ics = make_ics(vevent(
        UID="test-dur@example.com",
        DTSTART="20260615T130000Z",
        DURATION="PT2H",
        SUMMARY="Duration Event",
    ))
    cal = parse_ical_bytes(ics)
    bookings = parse_events_from_calendar(cal, EQ_ID, EQ_NAME)
    assert len(bookings) == 1
    b = bookings[0]
    assert b.end is not None
    assert b.duration_minutes == 120.0


# ---------------------------------------------------------------------------
# 4. Missing SUMMARY — should fall back to "Untitled booking"
# ---------------------------------------------------------------------------

def test_missing_summary_uses_default():
    ics = make_ics(vevent(
        UID="test-nosummary@example.com",
        DTSTART="20260615T090000Z",
        DTEND="20260615T110000Z",
    ))
    cal = parse_ical_bytes(ics)
    bookings = parse_events_from_calendar(cal, EQ_ID, EQ_NAME)
    assert bookings[0].title == "Untitled booking"


# ---------------------------------------------------------------------------
# 5. Missing DTSTART — event must be skipped (no crash)
# ---------------------------------------------------------------------------

def test_missing_dtstart_is_skipped():
    ics = make_ics(vevent(
        UID="test-nostart@example.com",
        SUMMARY="No Start Event",
    ))
    cal = parse_ical_bytes(ics)
    bookings = parse_events_from_calendar(cal, EQ_ID, EQ_NAME)
    assert bookings == []


def test_missing_dtstart_raises_in_component_to_booking():
    ics = make_ics(vevent(
        UID="test-nostart@example.com",
        SUMMARY="No Start Event",
    ))
    cal = parse_ical_bytes(ics)
    for component in cal.walk():
        if component.name == "VEVENT":
            with pytest.raises(CalendarParseError, match="DTSTART"):
                component_to_booking(component, EQ_ID, EQ_NAME)


# ---------------------------------------------------------------------------
# 6. All-day event (VALUE=DATE) — must be converted to datetime
# ---------------------------------------------------------------------------

def test_all_day_event_converted_to_datetime():
    ics = make_ics(
        "BEGIN:VEVENT\r\nUID:allday@example.com\r\n"
        "DTSTART;VALUE=DATE:20260615\r\n"
        "DTEND;VALUE=DATE:20260616\r\n"
        "SUMMARY:All Day Event\r\nEND:VEVENT"
    )
    cal = parse_ical_bytes(ics)
    bookings = parse_events_from_calendar(cal, EQ_ID, EQ_NAME)
    assert len(bookings) == 1
    b = bookings[0]
    assert isinstance(b.start, datetime)
    assert b.start.date() == date(2026, 6, 15)


# ---------------------------------------------------------------------------
# 7. Recurring event — is_recurring flag must be set
# ---------------------------------------------------------------------------

def test_recurring_event_flag():
    ics = make_ics(vevent(
        UID="test-rrule@example.com",
        DTSTART="20260615T090000Z",
        DTEND="20260615T100000Z",
        **{"RRULE": "FREQ=WEEKLY;COUNT=4"},
        SUMMARY="Weekly Event",
    ))
    cal = parse_ical_bytes(ics)
    bookings = parse_events_from_calendar(cal, EQ_ID, EQ_NAME)
    assert len(bookings) == 1
    assert bookings[0].is_recurring is True


# ---------------------------------------------------------------------------
# 8. Custom X-* fields are preserved in vendor_fields
# ---------------------------------------------------------------------------

def test_custom_x_fields_preserved():
    ics = make_ics(
        "BEGIN:VEVENT\r\n"
        "UID:test-x@example.com\r\n"
        "DTSTART:20260615T090000Z\r\n"
        "DTEND:20260615T110000Z\r\n"
        "SUMMARY:PPMS Booking\r\n"
        "X-PPMS-BOOKING-ID:12345\r\n"
        "X-PPMS-EQUIPMENT-ID:SEM-01\r\n"
        "END:VEVENT"
    )
    cal = parse_ical_bytes(ics)
    bookings = parse_events_from_calendar(cal, EQ_ID, EQ_NAME)
    b = bookings[0]
    assert "X-PPMS-BOOKING-ID" in b.vendor_fields
    assert b.vendor_fields["X-PPMS-BOOKING-ID"] == "12345"
    assert "X-PPMS-EQUIPMENT-ID" in b.vendor_fields
    # raw_properties should contain everything
    assert "SUMMARY" in b.raw_properties


# ---------------------------------------------------------------------------
# 9. Multiple equipment — one fails, others still parse
# ---------------------------------------------------------------------------

def test_multiple_equipment_one_fails():
    equipment = [
        EquipmentCalendar("sem-01", "SEM 01", "https://good.example.com/sem.ics"),
        EquipmentCalendar("tem-01", "TEM 01", "https://bad.example.com/tem.ics"),
    ]
    good_data = FIXTURE.read_bytes()

    def mock_fetch(url: str, timeout: int = 20) -> bytes:
        if "bad.example.com" in url:
            raise CalendarFetchError("Simulated network failure")
        return good_data

    with patch("lab_flightboard.ical_parser.fetch_ical_from_url", side_effect=mock_fetch):
        bookings, errors = parse_all_equipment(equipment)

    assert len(bookings) == 3          # 3 events from the good calendar
    assert len(errors) == 1
    assert errors[0]["equipment_id"] == "tem-01"
    assert "Simulated network failure" in errors[0]["error"]


# ---------------------------------------------------------------------------
# Fixture-based integration tests
# ---------------------------------------------------------------------------

def test_fixture_parses_all_events():
    data = FIXTURE.read_bytes()
    cal = parse_ical_bytes(data)
    bookings = parse_events_from_calendar(cal, "sem-01", "SEM 01")
    assert len(bookings) == 3


def test_fixture_booking_001_fields():
    data = FIXTURE.read_bytes()
    cal = parse_ical_bytes(data)
    bookings = parse_events_from_calendar(cal, "sem-01", "SEM 01")
    b = next(b for b in bookings if b.uid == "booking-001@example.com")
    assert b.title == "SEM Training Session"
    assert b.location == "Electron Microscopy Lab"
    assert b.status == "CONFIRMED"
    assert b.organiser == "facility@example.edu"
    assert "Training" in b.categories
    assert b.vendor_fields.get("X-PPMS-BOOKING-ID") == "12345"


def test_fixture_booking_002_uses_duration():
    data = FIXTURE.read_bytes()
    cal = parse_ical_bytes(data)
    bookings = parse_events_from_calendar(cal, "sem-01", "SEM 01")
    b = next(b for b in bookings if b.uid == "booking-002@example.com")
    assert b.end is not None
    assert b.duration_minutes == 120.0


def test_fixture_booking_003_is_recurring():
    data = FIXTURE.read_bytes()
    cal = parse_ical_bytes(data)
    bookings = parse_events_from_calendar(cal, "sem-01", "SEM 01")
    b = next(b for b in bookings if b.uid == "booking-003@example.com")
    assert b.is_recurring is True


# ---------------------------------------------------------------------------
# CalendarBooking helper methods
# ---------------------------------------------------------------------------

def test_is_current_true():
    now = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
    b = _booking(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 15, 11, 0, tzinfo=timezone.utc),
    )
    assert b.is_current(now) is True


def test_is_current_false_before():
    now = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
    b = _booking(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 15, 11, 0, tzinfo=timezone.utc),
    )
    assert b.is_current(now) is False


def test_is_current_false_after():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    b = _booking(
        start=datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 15, 11, 0, tzinfo=timezone.utc),
    )
    assert b.is_current(now) is False


def _booking(**kwargs):
    defaults = dict(
        uid="x",
        equipment_id="eq-01",
        equipment_name="EQ 01",
        title="Test",
        start=datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    from lab_flightboard.models import CalendarBooking
    return CalendarBooking(**defaults)
