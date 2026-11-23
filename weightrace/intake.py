from .codec import canonical, digest, loads
from .errors import Problem
from .sessions import advance, get_session
from .values import credential, fields, identifier, instant, integer, now

MAX_PACKETS = 100
MAX_PENDING = 100
MAX_READINGS = 200

# Round credentials and delivery receipts are transport metadata.  Older clients
# send bare packets; accept the common aliases so a receiver does not have to
# rewrite what the collector handed over.
ROUND_KEYS = ("round", "round_key", "round_id", "round_credential", "round_token",
              "round_no", "pass", "pass_id", "iteration", "batch", "cycle")
RECEIPT_KEYS = ("receipt", "delivery_receipt", "receipt_id", "receipt_token", "receipt_no",
                "handover_receipt", "delivery_id", "delivery_note", "handover", "handover_id")
DISPOSITION_KEYS = ("disposition", "resolution", "mode", "action")
DISPOSITIONS = {"claim": "claim", "retransmission": "retransmission", "retransmit": "retransmission",
                "close": "retransmission", "closed": "retransmission"}
PACKET_FIELDS = ("id", "rows", *ROUND_KEYS, *RECEIPT_KEYS)
CLAIM_FIELDS = (*ROUND_KEYS, *RECEIPT_KEYS, *DISPOSITION_KEYS, "retransmission")

# How a packet was attributed to a round, kept on the packet for the release file.
BASIS_LEGACY = "legacy"          # round-less session, the original intake behaviour
BASIS_CREDENTIAL = "credential"  # the packet itself carried a round credential
BASIS_CLAIMED = "claimed"        # receiver matched a held receipt to a round


def _single(item, names, label, maximum=64):
    present = [(name, item[name]) for name in names if item.get(name) not in (None, "")]
    if not present:
        return None
    value = credential(present[0][1], label, maximum)
    for name, other in present[1:]:
        if credential(other, label, maximum) != value:
            raise Problem("packet_meta", f"{label}字段互相矛盾", field=name)
    return value


def packet_meta(item):
    if not isinstance(item, dict):
        raise Problem("fields", "字段不完整或含未知字段", expected=list(PACKET_FIELDS))
    unknown = set(item) - set(PACKET_FIELDS)
    missing = {"id", "rows"} - set(item)
    if unknown or missing:
        raise Problem("fields", "字段不完整或含未知字段", expected=list(PACKET_FIELDS))
    return _single(item, ROUND_KEYS, "轮次凭据"), _single(item, RECEIPT_KEYS, "送交回执")


def parse_packet(item, plan):
    packet_meta(item)
    identifier(item["id"], "采集包编号")
    rows = item["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        raise Problem("packet_size", "每包须有 1 至 40 条读数")
    seen = set()
    steps = {step["id"] for step in plan["steps"]}
    for row in rows:
        fields(row, "id", "step", "observed_at", "indicated_mg")
        row_id = identifier(row["id"], "读数编号")
        if row_id in seen:
            raise Problem("duplicate_row", "包内读数编号重复", reading=row_id)
        seen.add(row_id)
        if identifier(row["step"], "步骤编号") not in steps:
            raise Problem("step", "读数引用了不在计划内的步骤", reading=row_id)
        if instant(row["observed_at"]).date().isoformat() != plan["measured_on"]:
            raise Problem("observation_day", "读数须采自计划的 UTC 日期", reading=row_id)
        value = integer(row["indicated_mg"], "原始示值", -10**10, 10**10)
        if value % plan["resolution_mg"]:
            raise Problem("resolution", "原始示值不在分度网格上", reading=row_id)
    # Package row order is transport metadata, not acquisition order.
    return {"id": item["id"], "rows": sorted(rows, key=lambda row: row["id"])}


def _round_aware(db, key):
    """True once a session is recognisably collecting by round.

    This covers filed round-stamped packets and receipts held for later claiming.
    Such a session must not silently attribute a bare packet to the legacy
    (round-less) bucket; the receiver has to supply a round credential or a
    delivery receipt so rolled-over packet numbers stay distinguishable.  A
    session that only ever sees bare packets keeps the original intake rules.
    """
    return bool(db.execute(
        "SELECT 1 FROM packets WHERE session=? AND round_key<>'' "
        "UNION ALL SELECT 1 FROM pending_packets WHERE session=? LIMIT 1", (key, key)).fetchone())


def _receipt_owner(db, key, receipt):
    return db.execute("SELECT round_key, id, digest FROM packets WHERE session=? AND receipt=?",
                      (key, receipt)).fetchone()


def _store_packet(db, key, packet, round_key, basis, receipt):
    checksum = digest(packet)
    if receipt:
        # A delivery receipt identifies one handover; the same receipt cannot carry
        # a second, different packet (or a different round) into the session.
        used = _receipt_owner(db, key, receipt)
        if used and (used["id"] != packet["id"] or used["round_key"] != round_key
                     or used["digest"] != checksum):
            raise Problem("receipt_conflict", "同回执送来的采集包内容不同", 409, receipt=receipt)
    previous = db.execute(
        "SELECT digest, round_basis, receipt FROM packets WHERE session=? AND round_key=? AND id=?",
        (key, round_key, packet["id"])).fetchone()
    if previous:
        if previous["digest"] != checksum:
            raise Problem("packet_conflict", "同轮同编号采集包内容不同", 409,
                          round=round_key, packet=packet["id"])
        # Same round, same number, same content: a retransmission, not a new packet.
        return {"id": packet["id"], "round": round_key, "round_basis": previous["round_basis"] or basis,
                "receipt": previous["receipt"] or receipt or "", "digest": checksum, "inserted": 0,
                "duplicate": True, "retransmission": True, "created": False}
    if db.execute("SELECT COUNT(*) FROM packets WHERE session=?", (key,)).fetchone()[0] >= MAX_PACKETS:
        raise Problem("packet_capacity", "该测次已达到采集包上限", 409)
    # Validate every row and the reading capacity before mutating so a conflict
    # never leaves a partial packet behind, even outside the HTTP transaction.
    fresh = []
    for row in packet["rows"]:
        values = (row["step"], row["observed_at"], row["indicated_mg"])
        old = db.execute("SELECT step, observed_at, indicated_mg FROM readings WHERE session=? AND id=?",
                         (key, row["id"])).fetchone()
        if old:
            if tuple(old) != values:
                raise Problem("row_conflict", "已归集的读数编号不能改写", 409, reading=row["id"])
        else:
            fresh.append(row["id"])
    readings = db.execute("SELECT COUNT(*) FROM readings WHERE session=?", (key,)).fetchone()[0]
    if readings + len(fresh) > MAX_READINGS:
        raise Problem("reading_capacity", "该测次超过读数上限，整包未归集", 409)
    db.execute("INSERT INTO packets(session, round_key, id, payload, digest, accepted_at, round_basis, receipt) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (key, round_key, packet["id"], canonical(packet), checksum, now(), basis, receipt or ""))
    inserted = 0
    for row in packet["rows"]:
        if row["id"] in fresh:
            db.execute("INSERT INTO readings(session, id, step, observed_at, indicated_mg, origin_round_key, origin_packet) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (key, row["id"], row["step"], row["observed_at"], row["indicated_mg"], round_key, packet["id"]))
            inserted += 1
        # Keep the row-to-packet link even when the reading already exists, so two
        # rounds carrying the same reading each retain their own source packet.
        db.execute("INSERT INTO packet_rows(session, round_key, packet, reading) VALUES (?, ?, ?, ?)",
                   (key, round_key, packet["id"], row["id"]))
    return {"id": packet["id"], "round": round_key, "round_basis": basis, "receipt": receipt or "",
            "digest": checksum, "inserted": inserted, "duplicate": False, "retransmission": False,
            "created": True}


def _pending_record(row, include_payload=False):
    record = {"receipt": row["receipt"], "id": row["id"], "digest": row["digest"],
              "received_at": row["received_at"], "status": row["status"], "round": row["round_key"],
              "resolved_at": row["resolved_at"]}
    if include_payload:
        record["payload"] = loads(row["payload"])
    return record


def _find_pending(db, key, receipt):
    return db.execute("SELECT * FROM pending_packets WHERE session=? AND receipt=?", (key, receipt)).fetchone()


def _resolve_pending(db, key, receipt, status, round_key):
    db.execute("UPDATE pending_packets SET status=?, round_key=?, resolved_at=? WHERE session=? AND receipt=?",
               (status, round_key, now(), key, receipt))


def _hold_pending(db, key, packet, receipt):
    checksum = digest(packet)
    previous = _find_pending(db, key, receipt)
    if previous:
        if previous["digest"] != checksum:
            raise Problem("receipt_conflict", "同回执送来的采集包内容不同", 409, receipt=receipt)
        result = {**_pending_record(previous), "pending": True, "duplicate": True, "inserted": 0}
        return result, False
    if db.execute("SELECT COUNT(*) FROM pending_packets WHERE session=? AND status='pending'",
                  (key,)).fetchone()[0] >= MAX_PENDING:
        raise Problem("pending_capacity", "待认领采集包已达上限", 409)
    received_at = now()
    db.execute("INSERT INTO pending_packets(session, receipt, id, payload, digest, received_at) "
               "VALUES (?, ?, ?, ?, ?, ?)",
               (key, receipt, packet["id"], canonical(packet), checksum, received_at))
    result = {"receipt": receipt, "id": packet["id"], "digest": checksum, "status": "pending",
              "round": "", "resolved_at": None, "received_at": received_at, "pending": True,
              "duplicate": False, "inserted": 0}
    return result, True


def _resolved_pending(db, key, pending, round_key):
    """Answer a repeated delivery of an already resolved receipt without redoing work."""
    if round_key is not None and round_key != pending["round_key"]:
        raise Problem("receipt_conflict", "同回执已归入另一轮次", 409,
                      receipt=pending["receipt"], round=pending["round_key"])
    record = _pending_record(pending)
    record.update({"pending": False, "duplicate": True, "inserted": 0,
                   "retransmission": pending["status"] == "retransmission", "resolved": pending["status"]})
    record["generation"] = get_session(db, key)[1]
    return record


def accept_packet(db, key, item):
    plan, generation = get_session(db, key)
    packet = parse_packet(item, plan)
    round_key, receipt = packet_meta(item)
    checksum = digest(packet)
    pending = _find_pending(db, key, receipt) if receipt else None
    if pending:
        if pending["digest"] != checksum:
            raise Problem("receipt_conflict", "同回执送来的采集包内容不同", 409, receipt=receipt)
        if pending["status"] != "pending":
            return _resolved_pending(db, key, pending, round_key)
        if round_key is None:
            # Nothing here identifies a round.  Re-sending the same receipt and
            # content is idempotent and never auto-claims on behalf of the receiver.
            result = {**_pending_record(pending), "pending": True, "duplicate": True, "inserted": 0}
            result["generation"] = generation
            return result
    if round_key is None:
        if receipt is not None:
            result, _ = _hold_pending(db, key, packet, receipt)
            result["generation"] = generation
            return result
        if _round_aware(db, key):
            raise Problem("round_required", "该测次按轮次收包，须提供轮次凭据或送交回执", 400)
        round_key = ""
    # A packet that names its own round is attributed by that credential, even when
    # it also happens to answer a held receipt; only a bare resend is "claimed".
    basis = BASIS_CREDENTIAL if round_key else BASIS_LEGACY
    record = _store_packet(db, key, packet, round_key, basis, receipt)
    created = record["created"]
    if pending:
        _resolve_pending(db, key, receipt, "claimed" if created else "retransmission", round_key)
        record["pending_resolved"] = "claimed" if created else "retransmission"
    record["generation"] = advance(db, key) if created else generation
    return record


def _claim_args(item):
    if not isinstance(item, dict):
        raise Problem("fields", "字段不完整或含未知字段", expected=list(CLAIM_FIELDS))
    unknown = set(item) - set(CLAIM_FIELDS)
    if unknown:
        raise Problem("fields", "字段不完整或含未知字段", expected=list(CLAIM_FIELDS))
    receipt = _single(item, RECEIPT_KEYS, "送交回执")
    round_key = _single(item, ROUND_KEYS, "轮次凭据")
    disposition = None
    for name in DISPOSITION_KEYS:
        if name in item:
            value = item[name]
            if not isinstance(value, str) or value not in DISPOSITIONS:
                raise Problem("disposition", "处理方式须为认领或同轮重传")
            disposition = DISPOSITIONS[value]
            break
    if disposition is None and item.get("retransmission") is True:
        disposition = "retransmission"
    return receipt, round_key, disposition or "claim"


def claim_pending(db, key, item, receipt=None):
    supplied, round_key, disposition = _claim_args(item or {})
    if receipt is not None and supplied is not None and credential(receipt, "送交回执") != supplied:
        raise Problem("receipt", "路径与请求体的送交回执不一致")
    receipt = supplied if supplied is not None else receipt
    if receipt is None:
        raise Problem("receipt", "须指定送交回执")
    receipt = credential(receipt, "送交回执")
    if round_key is None:
        raise Problem("round", "须指定要认领到的轮次")
    pending = _find_pending(db, key, receipt)
    if not pending:
        raise Problem("missing_pending", "待认领采集包不存在", 404, receipt=receipt)
    _, generation = get_session(db, key)
    if pending["status"] != "pending":
        return _resolved_pending(db, key, pending, round_key)
    packet = loads(pending["payload"])
    plan, _ = get_session(db, key)
    # Re-validate against the locked plan in case anything changed around the record.
    parse_packet(packet, plan)
    if disposition == "retransmission":
        # Closing a held retransmission must be corroborated by the original packet
        # already filed under this round, and must not contradict any reading it
        # carries.  Nothing new is stored; the held record keeps its audit trail.
        existing = db.execute("SELECT digest FROM packets WHERE session=? AND round_key=? AND id=?",
                              (key, round_key, packet["id"])).fetchone()
        if not existing or existing["digest"] != pending["digest"]:
            raise Problem("retransmission_unverified", "核对不到同轮同编号同内容的原包，不能按重传结案",
                          409, receipt=receipt, round=round_key, packet=packet["id"])
        for row in packet["rows"]:
            old = db.execute("SELECT step, observed_at, indicated_mg FROM readings WHERE session=? AND id=?",
                             (key, row["id"])).fetchone()
            if old and tuple(old) != (row["step"], row["observed_at"], row["indicated_mg"]):
                raise Problem("row_conflict", "读数编号在已归集批次中被改写", 409, reading=row["id"])
        _resolve_pending(db, key, receipt, "retransmission", round_key)
        return {"receipt": receipt, "status": "retransmission", "round": round_key,
                "id": packet["id"], "digest": pending["digest"], "generation": generation,
                "inserted": 0, "duplicate": True, "retransmission": True}
    record = _store_packet(db, key, packet, round_key, BASIS_CLAIMED, receipt)
    created = record["created"]
    status = "claimed" if created else "retransmission"
    # Resolve only after the packet is safely stored; a conflict rolls the whole
    # transaction back and leaves the pending record intact and queryable.
    _resolve_pending(db, key, receipt, status, round_key)
    record["receipt"] = receipt
    record["status"] = status
    record["generation"] = advance(db, key) if created else generation
    return record


def list_packets(db, key, include_payload=False):
    rows = db.execute("SELECT id, round_key, round_basis, receipt, digest, accepted_at, payload "
                      "FROM packets WHERE session=? ORDER BY round_key, id", (key,))
    result = []
    for row in rows:
        item = {"id": row["id"], "round": row["round_key"], "round_basis": row["round_basis"],
                "receipt": row["receipt"], "digest": row["digest"], "accepted_at": row["accepted_at"]}
        if include_payload:
            item["payload"] = loads(row["payload"])
        result.append(item)
    return result


def list_pending(db, key, include_payload=False):
    rows = db.execute("SELECT receipt, id, payload, digest, received_at, status, round_key, resolved_at "
                      "FROM pending_packets WHERE session=? ORDER BY received_at, receipt", (key,))
    return [_pending_record(row, include_payload) for row in rows]


def packet_sources(db, key):
    """Map each reading to every packet that carried it, with round provenance."""
    sources = {}
    rows = db.execute("""SELECT pr.reading, pr.round_key, pr.packet, p.round_basis, p.receipt
        FROM packet_rows pr JOIN packets p
          ON p.session=pr.session AND p.round_key=pr.round_key AND p.id=pr.packet
        WHERE pr.session=? ORDER BY pr.round_key, pr.packet""", (key,))
    for row in rows:
        sources.setdefault(row["reading"], []).append({
            "round": row["round_key"], "packet": row["packet"],
            "round_basis": row["round_basis"], "receipt": row["receipt"]})
    return sources


def pending_count(db, key):
    return db.execute("SELECT COUNT(*) FROM pending_packets WHERE session=? AND status='pending'",
                      (key,)).fetchone()[0]
