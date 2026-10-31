from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Quality(StrEnum):
    GOOD = "GOOD"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    BAD = "BAD"


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str
    value: float | None
    raw: int | None
    quality: Quality
    source_ts: datetime | None
    recv_ts: datetime
