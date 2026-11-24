from .adjudication import list_decisions, list_readings
from .alignment import align_steps
from .metrics import metric_inputs
from .protocol import steps_for
from .rounds import increment_band, list_rounds
from .sessions import get_session
from .verdict import classify_metrics, exact, outcome
from .zero_curve import zero_correct

ENGINE_V1 = "weightrace-linear-v1"
ENGINE = "weightrace-linear-v2"


def effective_plan(plan, round_record):
    if round_record["round"] == 0 or round_record["high_load"] == plan["loads"]["high"]:
        return plan
    loads = {**plan["loads"], "high": round_record["high_load"]}
    return {**plan, "loads": loads, "steps": steps_for(loads)}


def working_input(db, key):
    plan, generation = get_session(db, key)
    round_history = list_rounds(db, key)
    return {"plan": plan, "generation": generation, "rounds": round_history,
            "current_round": round_history[-1]["round"] if round_history else 0,
            "readings": list_readings(db, key), "decisions": list_decisions(db, key)}


def evaluate(snapshot):
    plan = snapshot["plan"]
    round_history = snapshot.get("rounds")
    # Frozen bundles written before round tracking carry no rounds; reproduce their v1 shape exactly.
    legacy = not round_history
    if legacy:
        current_round = 0
        round_record = {"round": 0, "high_load": plan["loads"]["high"]}
    else:
        current_round = snapshot.get("current_round", round_history[-1]["round"])
        round_record = next(record for record in round_history if record["round"] == current_round)
    active_plan = effective_plan(plan, round_record)
    steps, chosen, issues = align_steps(active_plan, snapshot["readings"], snapshot["decisions"], current_round)
    if legacy:
        for step in steps:
            step.pop("round", None)
    result = {"engine": ENGINE_V1 if legacy else ENGINE, "generation": snapshot["generation"],
              "steps": steps, "issues": issues}
    if not legacy:
        result = {"engine": ENGINE, "generation": snapshot["generation"], "current_round": current_round,
                  "rounds": round_history, "steps": steps, "issues": issues}
    if plan.get("increment_check"):
        increment = increment_band(active_plan["loads"]["low"], active_plan["loads"]["high"])
        result["increment_band"] = increment
    else:
        increment = None
    if issues:
        return {**result, "outcome": "blocked", "metrics": {}}
    corrected, drift = zero_correct(active_plan, chosen)
    for step in steps:
        point = corrected[step["id"]]
        step["zero"] = exact(point["zero"])
        step["corrected"] = exact(point["indication"])
        step["error"] = exact(point["error"])
    metrics = classify_metrics(metric_inputs(active_plan, corrected, drift, increment),
                               active_plan["limits_mg"])
    if increment is not None:
        metrics["increment"]["reference"] = {
            "reference_mg": exact(increment["reference_mg"]),
            "radius_mg": exact(increment["radius_mg"]),
            "lower_mg": exact(increment["reference_mg"] - increment["radius_mg"]),
            "upper_mg": exact(increment["reference_mg"] + increment["radius_mg"]),
            "shared_items": increment["shared_items"], "added_items": increment["added_items"]}
    return {**result, "metrics": metrics,
            "outcome": outcome([item["outcome"] for item in metrics.values()])}
