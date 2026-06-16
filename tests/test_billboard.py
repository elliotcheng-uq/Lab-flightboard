"""Tests for billboard status derivation and config loading.

All tests use fake CalendarBooking objects - no network, no real feeds.
"""
from datetime import datetime, timedelta, timezone

import pytest

from lab_flightboard.billboard import (
    auto_strip_terms,
    build_instrument_view,
    classify_incident,
    clean_title,
    current_booking,
    derive_status,
    email_local_part,
    format_name,
    is_active,
    next_booking,
    overlaps_business,
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


# Booking-system style titles: "<BUILDING INSTRUMENT> <Name> (<BUILDING INSTRUMENT>)"
def test_clean_title_strips_prefix_and_trailing_label():
    title = "BLDG-A SEM-1 Alex Taylor (BLDG-A SEM-1)"
    assert clean_title(title, None) == "Alex Taylor"


def test_clean_title_strips_userid_parens_with_configured_term():
    title = "BLDG-A SEM-2 Jordan Lee ( u1234567 )"
    assert clean_title(title, "BLDG-A SEM-2") == "Jordan Lee"


def test_clean_title_keeps_parens_when_disabled():
    title = "Alex (BLDG-A)"
    assert clean_title(title, None, strip_parentheses=False) == "Alex (BLDG-A)"


def test_auto_strip_terms_finds_repeated_label():
    titles = [
        "BLDG-A SEM-2 Jordan Lee ( u1234567 )",
        "BLDG-A SEM-2 Sam Carter (BLDG-A SEM-2)",
        "BLDG-A SEM-2 Priya Singh ( u7654321 ) (BLDG-A SEM-2)",
    ]
    terms = auto_strip_terms(titles)
    assert "BLDG-A SEM-2" in terms
    # Unique user ids should NOT be treated as strip terms
    assert "u1234567" not in terms


def test_auto_strip_terms_then_clean_handles_userid_only_booking():
    titles = [
        "BLDG-A SEM-2 Jordan Lee ( u1234567 )",
        "BLDG-A SEM-2 Sam Carter (BLDG-A SEM-2)",
        "BLDG-A SEM-2 Wei Chen (BLDG-A SEM-2)",
    ]
    terms = auto_strip_terms(titles)
    # The userid-only booking is cleaned thanks to the label learned from peers
    assert clean_title(titles[0], terms) == "Jordan Lee"


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


def test_classify_incident_by_link_pattern():
    b = booking(-1, 1, title="Some booking")
    b.raw_properties["URL"] = "https://booking.example.edu/inc/123"
    assert classify_incident(b, INCIDENT_CATS, incident_link_patterns=["/inc/"]) is True


def test_classify_incident_link_pattern_in_description():
    b = booking(-1, 1, title="Some booking")
    b.description = "See https://booking.example.edu/inc/123 for details"
    assert classify_incident(b, INCIDENT_CATS, incident_link_patterns=["/inc/"]) is True


def test_classify_link_pattern_not_matched():
    b = booking(-1, 1, title="Normal booking")
    b.raw_properties["URL"] = "https://booking.example.edu/booking/123"
    assert classify_incident(b, INCIDENT_CATS, incident_link_patterns=["/inc/"]) is False


def test_link_pattern_drives_status_and_view():
    b = booking(-1, 5, title="SEM-2 outage")
    b.raw_properties["URL"] = "https://booking.example.edu/inc/999"
    view = build_instrument_view(
        "eq", "EQ", [b], [], NOW, UTC, INCIDENT_CATS,
        incident_link_patterns=["/inc/"],
    )
    assert view.status == "down"
    assert len(view.incidents) == 1


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
# current / next booking helpers
# ---------------------------------------------------------------------------

def test_current_booking_returns_active():
    bookings = [booking(-1, 1, title="Now"), booking(2, 3, title="Later")]
    assert current_booking(bookings, NOW).title == "Now"


def test_current_booking_none_when_free():
    bookings = [booking(2, 3, title="Later")]
    assert current_booking(bookings, NOW) is None


def test_next_booking_returns_soonest_upcoming():
    bookings = [booking(5, 6, title="Evening"), booking(2, 3, title="Soon")]
    assert next_booking(bookings, NOW).title == "Soon"


def test_next_booking_none_when_nothing_upcoming():
    bookings = [booking(-3, -2, title="Past")]
    assert next_booking(bookings, NOW) is None


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


def test_equipment_id_optional_derived_from_name():
    cfg = parse_billboard_config({
        "instruments": [{"equipment_name": "SEM 01", "calendar_url": "demo://free"}]
    })
    assert cfg.instruments[0].equipment_id == "sem-01"


def test_calendar_url_optional_does_not_crash():
    cfg = parse_billboard_config({
        "instruments": [{"equipment_name": "Carbon Coater", "incidents_only": True}]
    })
    assert cfg.instruments[0].calendar_url == ""


def test_parse_config_requires_name():
    with pytest.raises(BillboardConfigError, match="equipment_name"):
        parse_billboard_config({
            "instruments": [{"calendar_url": "demo://free"}]
        })


def test_parse_display_options():
    cfg = parse_billboard_config({
        "instruments": [],
        "display_options": {
            "show_user_id": True,
            "show_email": True,
            "name_display": "initials",
            "day_window": "business",
            "business_start": "08:00",
            "business_end": "17:00",
        },
    })
    opts = cfg.display_options
    assert opts.show_user_id is True
    assert opts.name_display == "initials"
    assert opts.day_window == "business"
    assert opts.business_start == "08:00"


def test_display_options_default_when_absent():
    cfg = parse_billboard_config({"instruments": []})
    assert cfg.display_options.name_display == "full"
    assert cfg.display_options.day_window == "full"
    assert cfg.display_options.show_email is False


def test_parse_config_rejects_bad_name_display():
    with pytest.raises(BillboardConfigError, match="name_display"):
        parse_billboard_config({
            "instruments": [],
            "display_options": {"name_display": "shouting"},
        })


def test_parse_config_rejects_bad_day_window():
    with pytest.raises(BillboardConfigError, match="day_window"):
        parse_billboard_config({
            "instruments": [],
            "display_options": {"day_window": "midnight"},
        })


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def test_format_name_full():
    assert format_name("Alice Researcher", "full") == "Alice Researcher"


def test_format_name_initials():
    assert format_name("Alice Researcher", "initials") == "A. R."


def test_format_name_initials_single_word():
    assert format_name("Madonna", "initials") == "M."


def test_email_local_part():
    assert email_local_part("a.smith@example.edu") == "a.smith"


def test_email_local_part_none():
    assert email_local_part(None) is None


def test_overlaps_business_inside():
    b = booking(2, 3)  # NOW=10:00 UTC, so 12:00-13:00
    assert overlaps_business(b, UTC, "09:00", "18:00") is True


def test_overlaps_business_outside():
    b = booking(-3, -2)  # 07:00-08:00 UTC
    assert overlaps_business(b, UTC, "09:00", "18:00") is False


def test_overlaps_business_straddling_start():
    # 08:30-09:30 overlaps a 09:00 start
    b = CalendarBooking(
        uid="x", equipment_id="e", equipment_name="E", title="T",
        start=datetime(2026, 6, 15, 8, 30, tzinfo=UTC),
        end=datetime(2026, 6, 15, 9, 30, tzinfo=UTC),
    )
    assert overlaps_business(b, UTC, "09:00", "18:00") is True


def test_parse_instrument_room():
    cfg = parse_billboard_config({
        "instruments": [
            {"equipment_id": "a", "equipment_name": "A", "calendar_url": "demo://free", "room": "Room 1.01"}
        ]
    })
    assert cfg.instruments[0].room == "Room 1.01"


def test_parse_instrument_room_optional():
    cfg = parse_billboard_config({
        "instruments": [
            {"equipment_id": "a", "equipment_name": "A", "calendar_url": "demo://free"}
        ]
    })
    assert cfg.instruments[0].room is None


def test_parse_instrument_incidents_only():
    cfg = parse_billboard_config({
        "instruments": [
            {"equipment_id": "a", "equipment_name": "A", "calendar_url": "demo://incident", "incidents_only": True}
        ]
    })
    assert cfg.instruments[0].incidents_only is True


def test_incident_link_patterns_default():
    cfg = parse_billboard_config({"instruments": []})
    assert cfg.incident_link_patterns == ["/inc/"]


def test_incident_link_patterns_override():
    cfg = parse_billboard_config({
        "instruments": [],
        "incident_link_patterns": ["/inc/", "/intervention/"],
    })
    assert "/intervention/" in cfg.incident_link_patterns


def test_strip_parentheses_default_true():
    cfg = parse_billboard_config({"instruments": []})
    assert cfg.display_options.strip_parentheses is True


def test_strip_parentheses_can_disable():
    cfg = parse_billboard_config({
        "instruments": [],
        "display_options": {"strip_parentheses": False},
    })
    assert cfg.display_options.strip_parentheses is False


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
