from .adjudication import list_decisions, list_readings
from .alignment import align_steps
from .metrics import metric_inputs
from .sessions import get_session
from .verdict import classify_metrics, exact, outcome
from .zero_curve import segment_corrections

ENGINE = "weightrace-linear-segmented-v2"


def working_input(db, key):
    plan, generation = get_session(db, key)
    return {"plan": plan, "generation": generation, "readings": list_readings(db, key),
            "decisions": list_decisions(db, key)}


def evaluate(snapshot):
    plan = snapshot["plan"]
    steps, chosen, issues = align_steps(plan, snapshot["readings"], snapshot["decisions"])
    result = {"engine": ENGINE, "generation": snapshot["generation"], "steps": steps, "issues": issues}
    if issues:
        return {**result, "outcome": "blocked", "metrics": {}, "segments": []}
    corrected, drifts = segment_corrections(plan, chosen)
    for step in steps:
        point = corrected[step["id"]]
        step["zero"] = exact(point["zero"])
        step["corrected"] = exact(point["indication"])
        step["error"] = exact(point["error"])
        step["segment"] = point["segment"]
    metrics = classify_metrics(metric_inputs(plan, corrected, drifts), plan["limits_mg"])
    segments = [{"id": segment_id, "drift": exact(info["drift"]), "anchors": info["anchors"],
                 "span_seconds": info["span_seconds"]} for segment_id, info in sorted(drifts.items())]
    return {**result, "metrics": metrics, "segments": segments,
            "outcome": outcome([item["outcome"] for item in metrics.values()])}
