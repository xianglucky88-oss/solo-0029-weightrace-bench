from .archives import list_releases
from .evaluation import evaluate, working_input
from .intake import list_packets


def read_workbench(db, key):
    snapshot = working_input(db, key)
    releases = list_releases(db, key)
    state = "draft" if not releases else "released" if releases[0]["generation"] == snapshot["generation"] else "amended"
    if state == "released" and releases[0]["reason"]:
        state = "withdrawn"
    return {"plan": snapshot["plan"], "generation": snapshot["generation"],
            "current_round": snapshot["current_round"], "rounds": snapshot["rounds"],
            "state": state, "result": evaluate(snapshot),
            "decisions": snapshot["decisions"], "packets": list_packets(db, key), "releases": releases}
