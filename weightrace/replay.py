from . import legacy
from .codec import canonical, digest
from .evaluation import ENGINE, evaluate
from .handoff import RISE_KEYS

ENGINES = {ENGINE, legacy.ENGINE}


def replay(record):
    body = record["body"]
    if digest(body) != record["sha256"] or any(digest(packet["payload"]) != packet["digest"] for packet in body["packets"]):
        return {"verified": False, "reason": "digest_mismatch"}
    engine = body["result"]["engine"]
    if body["format"] != "weightrace-evidence-v1" or engine not in ENGINES:
        return {"verified": False, "reason": "unsupported_engine"}
    computed = (evaluate if engine == ENGINE else legacy.evaluate)(body["input"])
    if canonical(computed) != canonical(body["result"]):
        return {"verified": False, "reason": "result_mismatch", "sha256": record["sha256"]}
    # Re-derive the hand-off check from the sealed inputs, never from live state.
    handoff = body.get("handoff")
    if handoff is not None:
        if not handoff.get("document") or not handoff.get("status") or not handoff["status"].get("valid"):
            return {"verified": False, "reason": "handoff_invalid", "sha256": record["sha256"]}
        sealed = {step["id"]: step["selected"] for step in body["result"]["steps"]}
        if {name: sealed.get(name) for name in RISE_KEYS} != handoff["document"]["readings"]:
            return {"verified": False, "reason": "handoff_mismatch", "sha256": record["sha256"]}
    return {"verified": True, "reason": "matched", "sha256": record["sha256"]}
