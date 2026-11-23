from collections import defaultdict


def align_steps(plan, readings, decisions, review=None):
    latest = {decision["reading"]: decision for decision in decisions}
    by_step = defaultdict(list)
    for reading in readings:
        by_step[reading["step"]].append(reading)
    checks, chosen, issues = [], {}, []
    previous = None
    for step in plan["steps"]:
        key = step["id"]
        candidates = [{**row, "decision": latest.get(row["id"])} for row in by_step[key]]
        # With two or more left-offset candidates, only a confirmed dual review selects;
        # single-row decisions no longer count for this step.
        dual = review is not None and review["required"] and key == review["step"]
        if dual:
            eligible = [row for row in candidates if row["id"] == review["selection"]]
        else:
            eligible = [row for row in candidates if not row["decision"] or row["decision"]["action"] == "include"]
        state = "matched"
        if len(eligible) != 1:
            state = "review" if dual else "ambiguous" if eligible else "missing"
            issues.append({"code": state, "step": key,
                           "readings": [row["id"] for row in (candidates if dual else eligible)]})
        else:
            row = eligible[0]
            if previous and row["observed_at"] <= previous["observed_at"]:
                state = "out_of_order"
                issues.append({"code": state, "step": key, "readings": [previous["id"], row["id"]]})
            previous = row
            chosen[key] = row
        checks.append({**step, "state": state, "candidates": candidates,
                       "selected": eligible[0]["id"] if len(eligible) == 1 else None})
    return checks, chosen, issues
