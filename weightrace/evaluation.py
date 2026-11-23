from .adjudication import list_decisions, list_readings
from .alignment import align_steps
from .intake import packet_sources, pending_count
from .metrics import metric_inputs
from .sessions import get_session
from .verdict import classify_metrics, exact, outcome
from .zero_curve import zero_correct

ENGINE = "weightrace-linear-v1"


def working_input(db, key):
    plan, generation = get_session(db, key)
    return {"plan": plan, "generation": generation, "readings": list_readings(db, key),
            "decisions": list_decisions(db, key), "origins": packet_sources(db, key),
            "pending": pending_count(db, key)}


def evaluate(snapshot):
    plan = snapshot["plan"]
    steps, chosen, issues = align_steps(plan, snapshot["readings"], snapshot["decisions"],
                                        snapshot.get("origins"))
    result = {"engine": ENGINE, "generation": snapshot["generation"], "steps": steps, "issues": issues}
    # Unclaimed packets are excluded from the calculation, but they may still add
    # evidence that conflicts with an already selected reading.  Surface them as a
    # blocking issue so the workbench never presents a complete-looking session as
    # ready to sign while a held packet is unresolved.
    pending = snapshot.get("pending") or 0
    if pending:
        issues = [*issues, {"code": "pending_intake", "step": None, "readings": [], "pending": pending}]
        result["issues"] = issues
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
