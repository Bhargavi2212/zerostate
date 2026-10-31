from pydantic import BaseModel, ConfigDict

from zerostate.models.verdict import FindingStatus


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    rule_version: str
    status: FindingStatus
    message: str
    refs: list[str] = []
