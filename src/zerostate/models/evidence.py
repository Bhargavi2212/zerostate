from pydantic import BaseModel, ConfigDict

from zerostate.models.signal import Quality
from zerostate.models.verdict import FindingStatus


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    rule_version: str
    status: FindingStatus
    message: str
    refs: list[str] = []


Sample = tuple[float, float | None, int | None, Quality]  # (wall time s, value, raw, quality)


class Window(BaseModel):
    """The exact evidence a rule saw: logged inline with every evaluation, so replay re-runs it."""

    model_config = ConfigDict(extra="forbid")

    t0: float  # wall s of the step mark (process time 0 for this evaluation)
    t1: float  # wall s of the evaluation
    process_time_scale: float
    samples: dict[str, list[Sample]]
    spans: dict[str, tuple[float, float]] = {}  # tag -> (scale_min, scale_max) from the plant map
