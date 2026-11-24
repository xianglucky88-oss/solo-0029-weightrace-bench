"""De-identified review copies for external handoff.

A copy is derived from a frozen release through an explicit field allowlist:
workstation names, session numbers, packet numbers, reading numbers, standard
numbers and free text never enter the copy, and fields the internal release may
gain later (notes, memos) stay out unless deliberately added here. Pseudonyms
are salted with the release digest, which itself stays internal, so recipients
can tell sources apart without learning the original identifiers.
"""

import argparse
import hashlib
from pathlib import Path

from .archives import get_release
from .codec import canonical, digest, loads
from .errors import Problem
from .evaluation import ENGINE, evaluate
from .protocol import LIMIT_KEYS

FORMAT = "weightrace-review-copy-v1"
KIND_PREFIX = {"reading": "R", "packet": "P", "standard": "W"}


def pseudonym(salt, kind, original):
    token = hashlib.sha256(f"{FORMAT}/{kind}\n{salt}\n{original}".encode("utf-8")).hexdigest()
    return f"{KIND_PREFIX[kind]}-{token[:16]}"


def deidentified_copy(record):
    """Rebuild a frozen release as a reviewer copy, field by field."""
    body = record["body"]
    salt = record["sha256"]

    def reading_id(key):
        return pseudonym(salt, "reading", key)

    def packet_id(key):
        return pseudonym(salt, "packet", key)

    def decision_view(decision):
        if decision is None:
            return None
        return {"generation": decision["generation"], "reading": reading_id(decision["reading"]),
                "action": decision["action"], "made_at": decision["made_at"]}

    def reading_view(row):
        return {"id": reading_id(row["id"]), "step": row["step"], "observed_at": row["observed_at"],
                "indicated_mg": row["indicated_mg"], "origin_packet": packet_id(row["origin_packet"])}

    def load_view(load):
        return {"items": [{"id": pseudonym(salt, "standard", item["id"]), "revision": item["revision"],
                           "nominal_mg": item["nominal_mg"], "correction_mg": item["correction_mg"],
                           "radius_mg": item["radius_mg"], "valid_from": item["valid_from"],
                           "valid_until": item["valid_until"]} for item in load["items"]],
                "reference_mg": load["reference_mg"], "radius_mg": load["radius_mg"]}

    def step_view(step):
        view = {"id": step["id"], "label": step["label"], "load": step["load"],
                "reference_mg": step["reference_mg"], "radius_mg": step["radius_mg"],
                "state": step["state"], "selected": reading_id(step["selected"]) if step["selected"] else None,
                "candidates": [{**reading_view(row), "decision": decision_view(row["decision"])}
                               for row in step["candidates"]]}
        for key in ("zero", "corrected", "error"):
            if key in step:
                view[key] = step[key]
        return view

    plan = body["input"]["plan"]
    result = body["result"]
    packets = []
    for packet in body["packets"]:
        payload = {"id": packet_id(packet["id"]), "rows": [
            {"id": reading_id(row["id"]), "step": row["step"], "observed_at": row["observed_at"],
             "indicated_mg": row["indicated_mg"]} for row in packet["payload"]["rows"]]}
        packets.append({"id": payload["id"], "digest": digest(payload),
                        "accepted_at": packet["accepted_at"], "payload": payload})
    return {
        "format": FORMAT,
        "release": body["number"],
        "published_at": body["published_at"],
        "input": {
            "plan": {"measured_on": plan["measured_on"], "resolution_mg": plan["resolution_mg"],
                     "loads": {band: load_view(plan["loads"][band]) for band in ("zero", "low", "high")},
                     "limits_mg": {key: plan["limits_mg"][key] for key in LIMIT_KEYS},
                     "steps": [{"id": step["id"], "label": step["label"], "load": step["load"],
                                "reference_mg": step["reference_mg"], "radius_mg": step["radius_mg"]}
                               for step in plan["steps"]]},
            "generation": body["input"]["generation"],
            "readings": [reading_view(row) for row in body["input"]["readings"]],
            "decisions": [decision_view(item) for item in body["input"]["decisions"]],
        },
        "packets": packets,
        "result": {
            "engine": result["engine"], "generation": result["generation"],
            "steps": [step_view(step) for step in result["steps"]],
            "issues": [{"code": issue["code"], "step": issue["step"],
                        "readings": [reading_id(key) for key in issue["readings"]]}
                       for issue in result["issues"]],
            "metrics": {name: {"limit_mg": metric["limit_mg"], "outcome": metric["outcome"],
                               "checks": [{"center": check["center"], "lower": check["lower"],
                                           "upper": check["upper"], "steps": check["steps"],
                                           "outcome": check["outcome"]} for check in metric["checks"]]}
                        for name, metric in result["metrics"].items()},
            "outcome": result["outcome"],
        },
    }


def export_copy(db, key, number):
    record = get_release(db, key, number)
    if digest(record["body"]) != record["sha256"]:
        raise Problem("corrupt_release", "交付件摘要不一致，不能导出", 409)
    # The copy derives from the frozen body alone; the withdrawal register and
    # the original digest stay internal, and deriving never touches the release.
    body = deidentified_copy(record)
    stamp = digest(body)
    payload = canonical({"body": body, "copy_sha256": stamp}) + "\n"
    return payload.encode("utf-8"), f"weightrace-copy-r{number}-{stamp[:8]}.json"


def verify_copy(document):
    """Check a reviewer copy file without any access to the internal database."""
    if not isinstance(document, dict) or set(document) != {"body", "copy_sha256"}:
        return {"verified": False, "reason": "not_review_copy"}
    body, stamp = document["body"], document["copy_sha256"]
    if not isinstance(body, dict) or body.get("format") != FORMAT:
        return {"verified": False, "reason": "not_review_copy"}
    if not isinstance(stamp, str) or digest(body) != stamp:
        return {"verified": False, "reason": "digest_mismatch"}
    try:
        if body["result"]["engine"] != ENGINE:
            return {"verified": False, "reason": "unsupported_engine"}
        readings, packets = body["input"]["readings"], body["packets"]
        decisions = body["input"]["decisions"]
        reading_ids = {row["id"] for row in readings}
        packet_ids = {packet["id"] for packet in packets}
        if len(reading_ids) != len(readings) or len(packet_ids) != len(packets):
            return {"verified": False, "reason": "duplicate_pseudonym"}
        sources = {}
        for packet in packets:
            payload = packet["payload"]
            if payload["id"] != packet["id"] or digest(payload) != packet["digest"]:
                return {"verified": False, "reason": "broken_source"}
            sources[packet["id"]] = {row["id"] for row in payload["rows"]}
        by_id = {row["id"]: row for row in readings}
        for packet in packets:
            for row in packet["payload"]["rows"]:
                source = by_id.get(row["id"])
                if source is None or any(source[key] != row[key]
                                         for key in ("step", "observed_at", "indicated_mg")):
                    return {"verified": False, "reason": "broken_source"}
        for row in readings:
            if row["origin_packet"] not in packet_ids or row["id"] not in sources[row["origin_packet"]]:
                return {"verified": False, "reason": "broken_source"}
        for decision in decisions:
            if decision["reading"] not in reading_ids:
                return {"verified": False, "reason": "unknown_reading"}
        if canonical(evaluate(body["input"])) != canonical(body["result"]):
            return {"verified": False, "reason": "result_mismatch"}
    except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError, Problem):
        return {"verified": False, "reason": "malformed_copy"}
    return {"verified": True, "reason": "matched", "copy_sha256": stamp}


def main():
    parser = argparse.ArgumentParser(description="核验衡迹去标识复核副本，不访问内部工作库")
    parser.add_argument("copy", help="去标识副本 JSON 文件")
    args = parser.parse_args()
    try:
        document = loads(Path(args.copy).read_bytes())
    except (OSError, ValueError):
        print(canonical({"verified": False, "reason": "unreadable_file"}))
        return 2
    verdict = verify_copy(document)
    print(canonical(verdict))
    return 0 if verdict["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
