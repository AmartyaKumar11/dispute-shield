from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any


def paise_to_rupees(paise: int) -> float:
    return paise / 100


def unix_to_naive(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)


def jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    return obj
