from collections import defaultdict

from .protocol import CARRIED_STEPS


def align_steps(plan, readings, decisions, current_round):
    latest = {decision["reading"]: decision for decision in decisions}
    expected_round = {step["id"]: 0 if step["id"] in CARRIED_STEPS else current_round for step in plan["steps"]}
    by_step = defaultdict(list)
    for reading in readings:
        by_step[reading["step"]].append(reading)
    checks, chosen, issues = [], {}, []
    previous = None
    for step in plan["steps"]:
        key = step["id"]
        wanted_round = expected_round[key]
        candidates = [{**row, "decision": latest.get(row["id"])} for row in by_step[key]]
        # Readings from superseded rounds stay visible but can never serve the current round.
        eligible = [row for row in candidates
                    if row.get("round", 0) == wanted_round
                    and (not row["decision"] or row["decision"]["action"] == "include")]
        state = "matched"
        if len(eligible) != 1:
            state = "ambiguous" if eligible else "missing"
            issues.append({"code": state, "step": key, "readings": [row["id"] for row in eligible]})
        else:
            row = eligible[0]
            if previous and row["observed_at"] <= previous["observed_at"]:
                state = "out_of_order"
                issues.append({"code": state, "step": key, "readings": [previous["id"], row["id"]]})
            previous = row
            chosen[key] = row
        checks.append({**step, "state": state, "round": wanted_round, "candidates": candidates,
                       "selected": eligible[0]["id"] if len(eligible) == 1 else None})
    return checks, chosen, issues
