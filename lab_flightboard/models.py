from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CalendarBooking:
    uid: str
    equipment_id: str
    equipment_name: str
    title: str
    start: datetime
    end: Optional[datetime] = None
    status: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    organiser: Optional[str] = None
    categories: list[str] = field(default_factory=list)
    source_calendar_url: Optional[str] = None
    # Vendor / booking-system fields — not always present
    booking_reference: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    project: Optional[str] = None
    account_code: Optional[str] = None
    # Computed / derived
    is_cancelled: bool = False
    is_recurring: bool = False
    last_modified: Optional[datetime] = None
    created: Optional[datetime] = None
    sequence: Optional[int] = None
    # Raw storage for vendor-specific X-* fields and full property bag
    vendor_fields: dict = field(default_factory=dict)
    raw_properties: dict = field(default_factory=dict)

    @property
    def duration_minutes(self) -> Optional[float]:
        if self.start and self.end:
            return (self.end - self.start).total_seconds() / 60
        return None

    def is_current(self, now: Optional[datetime] = None) -> bool:
        """Return True if now falls within [start, end)."""
        now = now or datetime.now(timezone.utc)
        start = _ensure_aware(self.start)
        end = _ensure_aware(self.end) if self.end else None
        now = _ensure_aware(now)
        if start is None:
            return False
        if end is None:
            return start <= now
        return start <= now < end


@dataclass
class EquipmentCalendar:
    equipment_id: str
    equipment_name: str
    calendar_url: str
    location: Optional[str] = None
    display_order: Optional[int] = None
    enabled: bool = True


# ---------------------------------------------------------------------------
# Incident model (placeholder — not used by the parser yet)
# ---------------------------------------------------------------------------

@dataclass
class Incident:
    incident_id: str
    equipment_id: str
    equipment_name: str
    title: str
    severity: str          # info | warning | critical | maintenance
    status: str            # open | monitoring | resolved | cancelled
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None
    reported_by: Optional[str] = None
    resolved_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
