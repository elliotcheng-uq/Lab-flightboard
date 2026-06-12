import json
from pathlib import Path
from typing import Union

from .exceptions import EquipmentConfigError
from .models import EquipmentCalendar

_REQUIRED = ("equipment_id", "equipment_name", "calendar_url")


def load_equipment_config(path: Union[str, Path]) -> list[EquipmentCalendar]:
    """Load equipment calendar entries from a JSON file."""
    path = Path(path)
    if not path.exists():
        raise EquipmentConfigError(f"Config file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EquipmentConfigError(f"Invalid JSON in config file {path}: {exc}") from exc
    return _parse_config_list(raw)


def load_equipment_config_from_str(text: str) -> list[EquipmentCalendar]:
    """Load equipment calendar entries from a JSON string."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EquipmentConfigError(f"Invalid JSON: {exc}") from exc
    return _parse_config_list(raw)


def _parse_config_list(raw: object) -> list[EquipmentCalendar]:
    if not isinstance(raw, list):
        raise EquipmentConfigError("Equipment config must be a JSON array")
    entries: list[EquipmentCalendar] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise EquipmentConfigError(f"Entry {i} must be a JSON object")
        try:
            entries.append(_parse_entry(item))
        except EquipmentConfigError as exc:
            raise EquipmentConfigError(f"Entry {i} ({item.get('equipment_id', '?')}): {exc}") from exc
    return entries


def _parse_entry(item: dict) -> EquipmentCalendar:
    for key in _REQUIRED:
        if key not in item:
            raise EquipmentConfigError(f"Missing required field {key!r}")
    return EquipmentCalendar(
        equipment_id=str(item["equipment_id"]),
        equipment_name=str(item["equipment_name"]),
        calendar_url=str(item["calendar_url"]),
        location=item.get("location"),
        display_order=item.get("display_order"),
        enabled=bool(item.get("enabled", True)),
    )


def enabled_equipment(entries: list[EquipmentCalendar]) -> list[EquipmentCalendar]:
    """Return only enabled entries, sorted by display_order (None last)."""
    active = [e for e in entries if e.enabled]
    return sorted(active, key=lambda e: (e.display_order is None, e.display_order or 0))
