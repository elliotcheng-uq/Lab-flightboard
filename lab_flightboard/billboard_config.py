"""Loading and validation for the billboard configuration file.

The config is a single JSON object: global display settings plus a freeform
list of instruments (name + iCal URL). A future web admin form can write this
same JSON, so the schema is intentionally simple and tolerant.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .billboard import VALID_MODES
from .exceptions import BillboardConfigError

_REQUIRED_INSTRUMENT = ("equipment_id", "equipment_name", "calendar_url")

_DEFAULT_INCIDENT_CATEGORIES = ["Incident", "Intervention", "Maintenance", "Down"]


@dataclass
class BillboardInstrument:
    equipment_id: str
    equipment_name: str
    calendar_url: str
    incident_url: Optional[str] = None
    summary_strip: Optional[str] = None
    display_order: Optional[int] = None
    enabled: bool = True


@dataclass
class BillboardConfig:
    title: str = "Lab Flightboard"
    subtitle: str = "Instrument Status"
    timezone: str = "UTC"
    per_page: int = 6
    rotate_seconds: int = 20
    refresh_seconds: int = 60
    incident_lookahead_days: int = 30
    mode: str = "full"  # "full" | "status-only"
    incident_categories: list[str] = field(
        default_factory=lambda: list(_DEFAULT_INCIDENT_CATEGORIES)
    )
    incident_keywords: list[str] = field(default_factory=list)
    instruments: list[BillboardInstrument] = field(default_factory=list)


def load_billboard_config(path: Union[str, Path]) -> BillboardConfig:
    """Load and validate a billboard config JSON file."""
    path = Path(path)
    if not path.exists():
        raise BillboardConfigError(f"Config file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BillboardConfigError(f"Invalid JSON in {path}: {exc}") from exc
    return parse_billboard_config(raw)


def parse_billboard_config(raw: object) -> BillboardConfig:
    if not isinstance(raw, dict):
        raise BillboardConfigError("Billboard config must be a JSON object")

    mode = str(raw.get("mode", "full"))
    if mode not in VALID_MODES:
        raise BillboardConfigError(
            f"mode must be one of {VALID_MODES}, got {mode!r}"
        )

    instruments_raw = raw.get("instruments", [])
    if not isinstance(instruments_raw, list):
        raise BillboardConfigError("'instruments' must be a JSON array")

    instruments = [_parse_instrument(i, idx) for idx, i in enumerate(instruments_raw)]

    return BillboardConfig(
        title=str(raw.get("title", "Lab Flightboard")),
        subtitle=str(raw.get("subtitle", "Instrument Status")),
        timezone=str(raw.get("timezone", "UTC")),
        per_page=int(raw.get("per_page", 6)),
        rotate_seconds=int(raw.get("rotate_seconds", 20)),
        refresh_seconds=int(raw.get("refresh_seconds", 60)),
        incident_lookahead_days=int(raw.get("incident_lookahead_days", 30)),
        mode=mode,
        incident_categories=list(raw.get("incident_categories", _DEFAULT_INCIDENT_CATEGORIES)),
        incident_keywords=list(raw.get("incident_keywords", [])),
        instruments=instruments,
    )


def _parse_instrument(item: object, idx: int) -> BillboardInstrument:
    if not isinstance(item, dict):
        raise BillboardConfigError(f"Instrument {idx} must be a JSON object")
    for key in _REQUIRED_INSTRUMENT:
        if not item.get(key):
            raise BillboardConfigError(
                f"Instrument {idx} ({item.get('equipment_id', '?')}): missing required field {key!r}"
            )
    return BillboardInstrument(
        equipment_id=str(item["equipment_id"]),
        equipment_name=str(item["equipment_name"]),
        calendar_url=str(item["calendar_url"]),
        incident_url=item.get("incident_url"),
        summary_strip=item.get("summary_strip"),
        display_order=item.get("display_order"),
        enabled=bool(item.get("enabled", True)),
    )


def enabled_instruments(config: BillboardConfig) -> list[BillboardInstrument]:
    """Enabled instruments sorted by display_order (None last)."""
    active = [i for i in config.instruments if i.enabled]
    return sorted(
        active,
        key=lambda i: (i.display_order is None, i.display_order or 0),
    )
