"""Tests for billboard status derivation and config loading.

All tests use fake CalendarBooking objects - no network, no real feeds.
"""
from datetime import datetime, timedelta, timezone

import pytest

from lab_flightboard.billboard import (
    build_instrument_view,
    classify_incident,
    clean_title,
    derive_status,
    is_active,
)
from lab_flightboard.billboard_config import (
    enabled_instruments,
    parse_billboard_config,
)
from lab_flightboard.exceptions import BillboardConfigError
from lab_flightboard.models import CalendarBooking

UTC = timezone.utc
NOW = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
INCIDENT_CATS = ["Incident", "Maintenance"]


def booking(start_offset_h, end_offset_h, title="Booking", categories=None):
    return CalendarBooking(
        uid="x",
        equipment_id="eq-01",
        equipment_name="EQ 01",
        title=title,
        start=NOW + timedelta(hours=start_offset_h),
        end=NOW + timedelta(hours=end_offset_h),
        categories=categories or [],
    )


# ---------------------------------------------------------------------------
# clean_title
# ---------------------------------------------------------------------------

def test_clean_title_strips_trailing_parens():
    assert clean_title("A. Researcher (DEMO SEM)", "DEMO SEM") == "A. Researcher"


def test_clean_title_strips_leading_name():
    assert clean_title("DEMO SEM Jane Smith", "DEMO SEM") == "Jane Smith"


def test_clean_title_no_strip():
    assert clean_title("Plain Title", None) == "Plain Title"


def test_clean_title_empty_falls_back():
    assert clean_title("", None) == "Booked"


# ---------------------------------------------------------------------------
# is_active
# ---------------------------------------------------------------------------

def test_is_active_within_span():
    assert is_active(booking(-1, 1), NOW) is True


def test_is_active_before():
    assert is_active(booking(1, 2), NOW) is False


def test_is_active_after():
    assert is_active(booking(-2, -1), NOW) is False


# ---------------------------------------------------------------------------
# classify_incident
# ---------------------------------------------------------------------------

def test_classify_incident_by_category():
    b = booking(-1, 1, categories=["Maintenance"])
    assert classify_incident(b, INCIDENT_CATS) is True


def test_classify_incident_case_insensitive():
    b = booking(-1, 1, categories=["incident"])
    assert classify_incident(b, INCIDENT_CATS) is True


def test_classify_incident_by_keyword():
    b = booking(-1, 1, title="Vacuum fault")
    assert classify_incident(b, INCIDENT_CATS, incident_keywords=["fault"]) is True


def test_classify_normal_booking_is_not_incident():
    b = booking(-1, 1, title="Imaging session", categories=["Research"])
    assert classify_incident(b, INCIDENT_CATS) is False


# ---------------------------------------------------------------------------
# derive_status
# ---------------------------------------------------------------------------

def test_status_free_when_nothing_active():
    assert derive_status([booking(1, 2)], [], NOW) == "free"


def test_status_inuse_when_booking_active():
    assert derive_status([booking(-1, 1)], [], NOW) == "inuse"


def test_status_down_when_incident_active_beats_booking():
    bookings = [booking(-1, 1)]
    incidents = [booking(-1, 5, categories=["Incident"])]
    assert derive_status(bookings, incidents, NOW) == "down"


# ---------------------------------------------------------------------------
# build_instrument_view
# ---------------------------------------------------------------------------

def test_view_classifies_incident_from_booking_feed():
    events = [
        booking(-1, 1, title="Imaging"),
        booking(-1, 5, title="Down for repair", categories=["Maintenance"]),
    ]
    view = build_instrument_view(
        "eq-01", "EQ 01", events, [], NOW, UTC, INCIDENT_CATS
    )
    assert view.status == "down"
    assert len(view.incidents) == 1
    assert len(view.bookings) == 1


def test_view_separate_incident_feed():
    bookings = [booking(2, 3, title="Later booking")]
    incidents = [booking(-1, 4, title="Power outage")]
    view = build_instrument_view(
        "eq-01", "EQ 01", bookings, incidents, NOW, UTC, INCIDENT_CATS
    )
    assert view.status == "down"
    assert view.incidents[0].title == "Power outage"


def test_view_error_returns_nodata():
    view = build_instrument_view(
        "eq-01", "EQ 01", [], [], NOW, UTC, INCIDENT_CATS, error="boom"
    )
    assert view.status == "nodata"
    assert view.error == "boom"


def test_view_filters_to_today():
    # An event tomorrow should not appear in today's bookings
    tomorrow = booking(25, 26, title="Tomorrow")
    today = booking(1, 2, title="Today")
    view = build_instrument_view(
        "eq-01", "EQ 01", [tomorrow, today], [], NOW, UTC, INCIDENT_CATS
    )
    titles = [b.title for b in view.bookings]
    assert "Today" in titles
    assert "Tomorrow" not in titles


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def test_parse_minimal_config():
    cfg = parse_billboard_config({
        "instruments": [
            {"equipment_id": "a", "equipment_name": "A", "calendar_url": "demo://booking"}
        ]
    })
    assert cfg.title == "Lab Flightboard"
    assert len(cfg.instruments) == 1
    assert cfg.mode == "full"


def test_parse_config_rejects_bad_mode():
    with pytest.raises(BillboardConfigError, match="mode"):
        parse_billboard_config({"mode": "rainbow", "instruments": []})


def test_parse_config_requires_instrument_fields():
    with pytest.raises(BillboardConfigError, match="calendar_url"):
        parse_billboard_config({
            "instruments": [{"equipment_id": "a", "equipment_name": "A"}]
        })


def test_enabled_instruments_sorted_and_filtered():
    cfg = parse_billboard_config({
        "instruments": [
            {"equipment_id": "b", "equipment_name": "B", "calendar_url": "demo://free", "display_order": 2},
            {"equipment_id": "a", "equipment_name": "A", "calendar_url": "demo://free", "display_order": 1},
            {"equipment_id": "c", "equipment_name": "C", "calendar_url": "demo://free", "enabled": False},
        ]
    })
    active = enabled_instruments(cfg)
    assert [i.equipment_id for i in active] == ["a", "b"]
