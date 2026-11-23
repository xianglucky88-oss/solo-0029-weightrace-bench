from .codec import canonical, digest
from .evaluation import ENGINE, ENGINE_MULTISCALE, evaluate
from .sessions import is_multiscale

SUPPORTED_ENGINES = (ENGINE, ENGINE_MULTISCALE)


def verify_provenance(body):
    """Re-derive every adopted reading from the sealed raw packets.

    The download alone must let a successor trace each reading's declared scale
    and raw grids, recompute milligrams with the scale table locked at session
    opening, and detect any disagreement with the readings actually used.
    """
    plan = body["input"]["plan"]
    locked = {scale["id"]: scale["grid_mg"] for scale in plan["scales"]} if is_multiscale(plan) else None
    rows = {}
    for packet in body["packets"]:
        for row in packet["payload"]["rows"]:
            rows[row["id"]] = row
    for reading in body["input"]["readings"]:
        raw = rows.get(reading["id"])
        if raw is None:
            return False, "provenance_missing"
        if raw["step"] != reading["step"] or raw["observed_at"] != reading["observed_at"]:
            return False, "provenance_mismatch"
        if is_multiscale(plan):
            scale = raw.get("scale")
            grids = raw.get("grids")
            if scale not in locked or not isinstance(grids, int):
                return False, "provenance_mismatch"
            if scale != reading["scale"] or grids != reading["grids"]:
                return False, "provenance_mismatch"
            if grids * locked[scale] != reading["indicated_mg"]:
                return False, "provenance_mismatch"
        else:
            if "indicated_mg" not in raw or raw["indicated_mg"] != reading["indicated_mg"]:
                return False, "provenance_mismatch"
            if reading["indicated_mg"] % plan["resolution_mg"]:
                return False, "provenance_mismatch"
    # Every reading actually adopted by the plan must trace back to a sealed raw row.
    used = {step["selected"] for step in body["result"]["steps"] if step["selected"]}
    if used - set(rows):
        return False, "provenance_missing"
    return True, "matched"


def replay(record):
    body = record["body"]
    if digest(body) != record["sha256"] or any(digest(packet["payload"]) != packet["digest"] for packet in body["packets"]):
        return {"verified": False, "reason": "digest_mismatch"}
    if body["format"] != "weightrace-evidence-v1" or body["result"]["engine"] not in SUPPORTED_ENGINES:
        return {"verified": False, "reason": "unsupported_engine"}
    provenance, reason = verify_provenance(body)
    if not provenance:
        return {"verified": False, "reason": reason, "sha256": record["sha256"]}
    computed = evaluate(body["input"])
    verified = canonical(computed) == canonical(body["result"])
    return {"verified": verified, "reason": "matched" if verified else "result_mismatch", "sha256": record["sha256"]}
