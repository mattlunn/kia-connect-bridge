import dataclasses
import datetime as dt
from enum import Enum
from typing import Any

from hyundai_kia_connect_api import Vehicle

# The raw Kia/Hyundai payload, rather than anything the library maps.
EXCLUDED_VEHICLE_FIELDS = {"data"}

VEHICLE_PROPERTIES = [name for name, attr in vars(Vehicle).items() if isinstance(attr, property)]


def vehicle_to_json(vehicle: Vehicle) -> dict[str, Any]:
    names = [
        field.name
        for field in dataclasses.fields(vehicle)
        if not field.name.startswith("_") and field.name not in EXCLUDED_VEHICLE_FIELDS
    ]

    return {name: to_json(getattr(vehicle, name)) for name in sorted(names + VEHICLE_PROPERTIES)}


def to_json(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_json(getattr(value, field.name)) for field in dataclasses.fields(value)
        }

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()

    if isinstance(value, dt.tzinfo):
        return str(value)

    if isinstance(value, dict):
        return {str(key): to_json(item) for key, item in value.items()}

    if isinstance(value, list | tuple | set):
        return [to_json(item) for item in value]

    return value
