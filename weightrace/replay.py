from .codec import canonical, digest

from .evaluation import evaluate


def replay(record):
    body = record["body"]
    if digest(body) != record["sha256"] or any(digest(packet["payload"]) != packet["digest"] for packet in body["packets"]):
        return {"verified": False, "reason": "digest_mismatch"}
    if not body["format"].startswith("weightrace-evidence-"):
        return {"verified": False, "reason": "unsupported_engine"}
    computed = evaluate(body["input"])
    verified = canonical(computed) == canonical(body["result"])
    return {"verified": verified, "reason": "matched" if verified else "result_mismatch", "sha256": record["sha256"]}
