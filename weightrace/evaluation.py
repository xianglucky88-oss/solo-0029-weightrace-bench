from .adjudication import list_decisions, list_readings
from .alignment import align_steps
from .metrics import metric_inputs
from .reviews import list_opinions, review_round
from .sessions import get_session
from .verdict import classify_metrics, exact, outcome
from .zero_curve import zero_correct

ENGINE = "weightrace-linear-v1"


def working_input(db, key):
    plan, generation = get_session(db, key)
    return {"plan": plan, "generation": generation, "readings": list_readings(db, key),
            "decisions": list_decisions(db, key), "reviews": list_opinions(db, key)}


def evaluate(snapshot):
    plan = snapshot["plan"]
    # Bundles frozen before dual review existed carry no opinion log; replay them as frozen.
    opinions = snapshot.get("reviews")
    review = review_round(snapshot["readings"], opinions) if opinions is not None else None
    steps, chosen, issues = align_steps(plan, snapshot["readings"], snapshot["decisions"], review)
    result = {"engine": ENGINE, "generation": snapshot["generation"], "steps": steps, "issues": issues}
    if review is not None:
        result["review"] = review
    if issues:
        return {**result, "outcome": "blocked", "metrics": {}}
    corrected, drift = zero_correct(plan, chosen)
    for step in steps:
        point = corrected[step["id"]]
        step["zero"] = exact(point["zero"])
        step["corrected"] = exact(point["indication"])
        step["error"] = exact(point["error"])
    metrics = classify_metrics(metric_inputs(plan, corrected, drift), plan["limits_mg"])
    return {**result, "metrics": metrics, "outcome": outcome([item["outcome"] for item in metrics.values()])}
