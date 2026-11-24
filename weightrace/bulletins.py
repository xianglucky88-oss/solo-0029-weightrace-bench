from .codec import canonical, digest, loads
from .errors import Problem
from .protocol import LIMIT_KEYS
from .values import day, fields, identifier, integer, now

def register_bulletin(db, item):
    fields(item, "id", "effective_from", "effective_until", "limits_mg")
    key = identifier(item["id"], "公告编号")
    start = day(item["effective_from"])
    end = day(item["effective_until"])
    if start >= end:
        raise Problem("bulletin_range", "公告适用到期日须晚于起效日")
    fields(item["limits_mg"], *LIMIT_KEYS)
    limits = {name: integer(item["limits_mg"][name], name, 1, 1_000_000) for name in LIMIT_KEYS}
    document = {"id": key, "effective_from": start, "effective_until": end, "limits_mg": limits}
    checksum = digest(document)
    existing = db.execute("SELECT digest, document FROM bulletins WHERE id=?", (key,)).fetchone()
    if existing:
        if existing["digest"] == checksum:
            return loads(existing["document"]), False
        raise Problem("bulletin_conflict", "同编号公告内容不同，不予接受", 409)
    seq = db.execute("SELECT COALESCE(MAX(seq), 0)+1 FROM bulletins").fetchone()[0]
    published_at = now()
    db.execute("INSERT INTO bulletins(id, document, digest, seq, published_at) VALUES (?, ?, ?, ?, ?)",
               (key, canonical(document), checksum, seq, published_at))
    return document, True


def list_bulletins(db):
    return [loads(row["document"]) for row in
            db.execute("SELECT document FROM bulletins ORDER BY seq, id")]


def get_bulletin(db, key):
    row = db.execute("SELECT document FROM bulletins WHERE id=?", (key,)).fetchone()
    if not row:
        raise Problem("missing_bulletin", "找不到该限值公告", 404, bulletin=key)
    return loads(row["document"])


def resolve_basis(db, plan, as_of):
    """Pick the latest published bulletin whose [from, until) covers the measured day."""
    if plan.get("judgement") != "bulletin":
        return {"mode": "own", "limits_mg": plan["limits_mg"]}
    measured_on = plan["measured_on"]
    rows = db.execute("""SELECT document, published_at FROM bulletins
        WHERE json_extract(document, '$.effective_from') <= ?
          AND ? < json_extract(document, '$.effective_until')
          AND published_at <= ?
        ORDER BY seq DESC""", (measured_on, measured_on, as_of)).fetchall()
    if not rows:
        return {"mode": "bulletin", "bulletin": None, "measured_on": measured_on}
    return {"mode": "bulletin", "bulletin": loads(rows[0]["document"]),
            "published_at": rows[0]["published_at"], "measured_on": measured_on}
