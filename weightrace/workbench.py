from .archives import list_releases
from .evaluation import evaluate, working_input
from .handoff import list_handoffs, list_invalidations
from .intake import list_packets


def read_workbench(db, key):
    # Invalidation is recorded where evidence changes (intake, adjudication,
    # confirmation); reading the view only reports it, so a GET never writes.
    snapshot = working_input(db, key)
    releases = list_releases(db, key)
    state = "draft" if not releases else "released" if releases[0]["generation"] == snapshot["generation"] else "amended"
    if state == "released" and releases[0]["reason"]:
        state = "withdrawn"
    return {"plan": snapshot["plan"], "generation": snapshot["generation"], "state": state,
            "result": evaluate(snapshot), "decisions": snapshot["decisions"],
            "packets": list_packets(db, key), "releases": releases,
            "handoffs": list_handoffs(db, key), "invalidations": list_invalidations(db, key)}
