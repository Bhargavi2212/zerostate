from enum import StrEnum


class Verdict(StrEnum):
    # No SAFE member, by design: ZeroState can only object or find nothing.
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF = "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"


class FindingStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
