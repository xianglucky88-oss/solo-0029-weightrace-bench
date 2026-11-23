from .archives import get_release
from .codec import canonical, digest
from .errors import Problem


def export_release(db, key, number):
    record = get_release(db, key, number)
    if digest(record["body"]) != record["sha256"]:
        raise Problem("corrupt_release", "交付件摘要不一致，不能导出", 409)
    # The mutable withdrawal register is deliberately not part of the frozen file.
    payload = canonical({"body": record["body"], "sha256": record["sha256"]}) + "\n"
    return payload.encode("utf-8"), f"weightrace-{key}-r{number}.json"
