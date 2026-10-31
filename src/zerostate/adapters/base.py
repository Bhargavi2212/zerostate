from typing import Protocol

from zerostate.models.signal import Signal


class ReadOnlyAdapter(Protocol):
    """Plant access. Read only: no write method exists anywhere in this package."""

    def read(self, tags: list[str] | None = None) -> dict[str, Signal]: ...
