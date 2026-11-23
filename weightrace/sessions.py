from .codec import canonical, loads
from .errors import Problem
from .protocol import LIMIT_KEYS, steps_for
from .standards import resolve_load
from .values import day, fields, identifier, integer, text


def create_session(db, item):
    fields(item, "id", "bench", "measured_on", "resolution_mg", "loads", "limits_mg")
    key = identifier(item["id"], "测次编号")
    if db.execute("SELECT 1 FROM sessions WHERE id=?", (key,)).fetchone():
        raise Problem("session_exists", "测次编号已存在", 409)
    bench = text(item["bench"], "工位名称", 64)
    measured_on = day(item["measured_on"])
    resolution = integer(item["resolution_mg"], "分度值", 1, 100_000)
    fields(item["loads"], "low", "high")
    fields(item["limits_mg"], *LIMIT_KEYS)
    limits = {key: integer(item["limits_mg"][key], key, 1, 1_000_000) for key in LIMIT_KEYS}
    bands = {k: resolve_load(db, item["loads"][k], measured_on) for k in ("low", "high")}
    low = bands["low"]
    high = bands["high"]
    if low["reference_mg"] + low["radius_mg"] >= high["reference_mg"] - high["radius_mg"]:
        raise Problem("load_order", "低档与高档参考质量范围须严格分离")
    versions = {}
    for band in (low, high):
        for standard in band["items"]:
            revision = versions.setdefault(standard["id"], standard["revision"])
            if revision != standard["revision"]:
                raise Problem("standard_split", "同一实物在同测次不能使用不同凭据修订", id=standard["id"])
    bands["zero"] = {"items": [], "reference_mg": 0, "radius_mg": 0}
    plan = {"id": key, "bench": bench, "measured_on": measured_on, "resolution_mg": resolution,
            "loads": bands, "limits_mg": limits, "steps": steps_for(bands)}
    db.execute("INSERT INTO sessions(id, plan) VALUES (?, ?)", (key, canonical(plan)))
    return plan


def get_session(db, key):
    row = db.execute("SELECT plan, generation FROM sessions WHERE id=?", (key,)).fetchone()
    if not row:
        raise Problem("missing_session", "测次不存在", 404)
    return loads(row["plan"]), row["generation"]


def require_generation(expected, current):
    if integer(expected, "数据代次") != current:
        raise Problem("stale_generation", "数据已变更，请复核最新结果后重试", 409, current=current)


def advance(db, key):
    return db.execute("UPDATE sessions SET generation=generation+1 WHERE id=? RETURNING generation", (key,)).fetchone()[0]


def list_sessions(db):
    rows = db.execute("""SELECT s.plan, s.generation, MAX(r.generation) AS published_generation
        FROM sessions s LEFT JOIN releases r ON r.session=s.id
        GROUP BY s.id ORDER BY json_extract(s.plan, '$.measured_on') DESC, s.id""")
    return [{"id": plan["id"], "bench": plan["bench"], "measured_on": plan["measured_on"],
             "generation": row["generation"], "published_generation": row["published_generation"]}
            for row in rows for plan in (loads(row["plan"]),)]
