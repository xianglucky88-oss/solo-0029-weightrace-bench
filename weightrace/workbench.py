from .archives import list_releases
from .evaluation import evaluate, working_input
from .intake import list_packets, list_pending


def read_workbench(db, key):
    snapshot = working_input(db, key)
    releases = list_releases(db, key)
    pending = list_pending(db, key)
    waiting = sum(1 for record in pending if record["status"] == "pending")
    state = "draft" if not releases else "released" if releases[0]["generation"] == snapshot["generation"] else "amended"
    if state == "released" and releases[0]["reason"]:
        state = "withdrawn"
    # Pending packets do not advance the generation, so an already signed version
    # stays current; the block on a new version is carried by the result issues.
    return {"plan": snapshot["plan"], "generation": snapshot["generation"], "state": state,
            "result": evaluate(snapshot), "decisions": snapshot["decisions"],
            "packets": list_packets(db, key), "pending": pending, "pending_count": waiting,
            "releases": releases}
