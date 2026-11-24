from collections import defaultdict

from .protocol import RISE_SEGMENT


def _step_checks(plan, readings, decisions):
    latest = {decision["reading"]: decision for decision in decisions}
    by_step = defaultdict(list)
    for reading in readings:
        by_step[reading["step"]].append(reading)
    checks = {}
    for step in plan["steps"]:
        key = step["id"]
        candidates = [{**row, "decision": latest.get(row["id"])} for row in by_step[key]]
        eligible = [row for row in candidates if not row["decision"] or row["decision"]["action"] == "include"]
        checks[key] = {**step, "state": "matched" if len(eligible) == 1 else
                       "ambiguous" if eligible else "missing",
                       "candidates": candidates,
                       "selected": eligible[0]["id"] if len(eligible) == 1 else None,
                       "eligible": eligible}
    return checks


def align_steps(plan, readings, decisions):
    checks = _step_checks(plan, readings, decisions)
    ordered, chosen, issues = [], {}, []
    previous = None
    for step in plan["steps"]:
        key = step["id"]
        check = checks[key]
        eligible = check["eligible"]
        state = check["state"]
        if len(eligible) != 1:
            issues.append({"code": state, "step": key, "readings": [row["id"] for row in eligible]})
        else:
            row = eligible[0]
            if previous and row["observed_at"] <= previous["observed_at"]:
                state = "out_of_order"
                issues.append({"code": state, "step": key, "readings": [previous["id"], row["id"]]})
            previous = row
            chosen[key] = row
        ordered.append({**{name: check[name] for name in
                           ("id", "label", "load", "reference_mg", "radius_mg", "candidates", "selected")},
                        "state": state})
    return ordered, chosen, issues


def align_rise_segment(plan, readings, decisions):
    """Align only the stepped first segment up to the pre-reset pan.

    A hand-off covers the readings taken before the reset.  It requires the
    first pan, both rise indications and the pre-reset pan to each have exactly
    one eligible reading in strict time order, so the segment can be judged on
    its own even while the second segment is still arriving.
    """
    checks = _step_checks(plan, readings, decisions)
    order = [key for key in RISE_SEGMENT if key in checks]
    segment, chosen, issues, previous = [], {}, [], None
    for key in order:
        check = checks[key]
        eligible = check["eligible"]
        state = check["state"]
        if len(eligible) != 1:
            issues.append({"code": state, "step": key, "readings": [row["id"] for row in eligible]})
        else:
            row = eligible[0]
            if previous and row["observed_at"] <= previous["observed_at"]:
                state = "out_of_order"
                issues.append({"code": state, "step": key, "readings": [previous["id"], row["id"]]})
            previous = row
            chosen[key] = row
        segment.append({**{name: check[name] for name in
                           ("id", "label", "load", "reference_mg", "radius_mg", "candidates", "selected")},
                        "state": state})
    return segment, chosen, issues
