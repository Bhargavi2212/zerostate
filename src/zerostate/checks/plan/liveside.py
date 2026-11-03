"""PLAN-LIVESIDE (decision 8): the work is on a listed isolation device itself, or inside its boundary
(an instrument the map ties to that device, e.g. its actuator or limit switch). The device relied on
is then the one being opened (LyondellBasell 2021)."""

from zerostate.checks.plan import finding
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PLAN-LIVESIDE", "1"


def check(plan, m, params):
    work = plan.work.equipment
    listed = {p.tag for p in plan.points}
    part_of = next((i.point for i in m.instruments if i.tag == work and i.point in listed), None)
    if work in listed:
        return finding(RULE_ID, RULE_VERSION, S.FAIL, f"the work is on {work}, a listed isolation device: "
                       "the device relied on is the one being opened", refs=[work])
    if part_of:
        return finding(RULE_ID, RULE_VERSION, S.FAIL, f"the work on {work} is inside the boundary of listed "
                       f"isolation device {part_of}: the device relied on is the one being opened", refs=[part_of])
    return finding(RULE_ID, RULE_VERSION, S.PASS, f"{work} is not a listed isolation device or part of one")
