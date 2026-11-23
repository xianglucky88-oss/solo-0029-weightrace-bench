from .codec import canonical, loads
from .errors import Problem
from .values import day, fields, identifier, integer


def register_standard(db, item):
    fields(item, "id", "revision", "nominal_mg", "correction_mg", "radius_mg", "valid_from", "valid_until")
    key = identifier(item["id"], "砝码编号"), integer(item["revision"], "凭据修订", 1)
    nominal = integer(item["nominal_mg"], "标称质量", 1)
    correction = integer(item["correction_mg"], "修正量", -1_000_000, 1_000_000)
    radius = integer(item["radius_mg"], "不确定半径", 0, 1_000_000)
    if nominal + correction - radius <= 0:
        raise Problem("mass_interval", "参考质量范围必须全为正")
    if day(item["valid_from"]) >= day(item["valid_until"]):
        raise Problem("validity", "凭据到期日须晚于起效日")
    existing = db.execute("SELECT document FROM standards WHERE id=? AND revision=?", key).fetchone()
    if existing:
        if loads(existing[0]) == item:
            return item, False
        raise Problem("standard_conflict", "同编号同修订的凭据不能覆盖", 409)
    db.execute("INSERT INTO standards VALUES (?, ?, ?)", (*key, canonical(item)))
    return item, True


def list_standards(db):
    return [loads(row[0]) for row in db.execute("SELECT document FROM standards ORDER BY id, revision")]


def resolve_load(db, references, measured_on):
    if not isinstance(references, list) or not 1 <= len(references) <= 8:
        raise Problem("load", "每档须引用 1 至 8 件砝码凭据")
    items = {}
    for ref in references:
        fields(ref, "id", "revision")
        key = identifier(ref["id"], "砝码编号"), integer(ref["revision"], "凭据修订", 1)
        if key[0] in items:
            raise Problem("repeated_weight", "同档不能重复使用同一件砝码", id=key[0])
        row = db.execute("SELECT document FROM standards WHERE id=? AND revision=?", key).fetchone()
        if not row:
            raise Problem("missing_standard", "找不到指定砝码凭据", id=key[0], revision=key[1])
        item = loads(row[0])
        if not item["valid_from"] <= measured_on < item["valid_until"]:
            raise Problem("expired_standard", "指定凭据在测次日无效", id=key[0], revision=key[1])
        items[key[0]] = item
    return {
        "items": [items[key] for key in sorted(items)],
        "reference_mg": sum(v["nominal_mg"] + v["correction_mg"] for v in items.values()),
        "radius_mg": sum(v["radius_mg"] for v in items.values()),
    }
