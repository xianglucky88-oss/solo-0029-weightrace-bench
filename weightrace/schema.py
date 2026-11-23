VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS standards (
    id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
    PRIMARY KEY (id, revision)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, plan TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS packets (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    round_key TEXT NOT NULL DEFAULT '',
    id TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, accepted_at TEXT NOT NULL,
    round_basis TEXT NOT NULL DEFAULT '', receipt TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (session, round_key, id)
);
CREATE INDEX IF NOT EXISTS packets_round ON packets(session, round_key, id);
CREATE TABLE IF NOT EXISTS readings (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    id TEXT NOT NULL, step TEXT NOT NULL, observed_at TEXT NOT NULL, indicated_mg INTEGER NOT NULL,
    origin_round_key TEXT NOT NULL DEFAULT '', origin_packet TEXT NOT NULL,
    PRIMARY KEY (session, id),
    FOREIGN KEY (session, origin_round_key, origin_packet) REFERENCES packets(session, round_key, id)
);
CREATE INDEX IF NOT EXISTS readings_step ON readings(session, step, observed_at);
CREATE TABLE IF NOT EXISTS packet_rows (
    session TEXT NOT NULL, round_key TEXT NOT NULL, packet TEXT NOT NULL, reading TEXT NOT NULL,
    PRIMARY KEY (session, round_key, packet, reading),
    FOREIGN KEY (session, round_key, packet) REFERENCES packets(session, round_key, id),
    FOREIGN KEY (session, reading) REFERENCES readings(session, id)
);
CREATE INDEX IF NOT EXISTS packet_rows_reading ON packet_rows(session, reading);
CREATE TABLE IF NOT EXISTS pending_packets (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    receipt TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'retransmission')),
    round_key TEXT NOT NULL DEFAULT '', resolved_at TEXT,
    PRIMARY KEY (session, receipt)
);
CREATE INDEX IF NOT EXISTS pending_packets_status ON pending_packets(session, status, received_at);
CREATE TABLE IF NOT EXISTS decisions (
    session TEXT NOT NULL, generation INTEGER NOT NULL, reading TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('exclude', 'include')),
    reason TEXT NOT NULL, made_at TEXT NOT NULL, PRIMARY KEY (session, generation),
    FOREIGN KEY (session, reading) REFERENCES readings(session, id)
);
CREATE INDEX IF NOT EXISTS decisions_reading ON decisions(session, reading, generation);
CREATE TABLE IF NOT EXISTS releases (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    number INTEGER NOT NULL, generation INTEGER NOT NULL, published_at TEXT NOT NULL,
    digest TEXT NOT NULL, bundle TEXT NOT NULL,
    PRIMARY KEY (session, number), UNIQUE (session, generation)
);
CREATE TABLE IF NOT EXISTS withdrawals (
    session TEXT NOT NULL, number INTEGER NOT NULL, reason TEXT NOT NULL, withdrawn_at TEXT NOT NULL,
    PRIMARY KEY (session, number), FOREIGN KEY (session, number) REFERENCES releases(session, number)
);
"""

# Version 1 identified a packet by (session, id) only and kept no row-level
# provenance. Rebuild the packet/reading tables so a rolled-over packet number can
# exist once per round, while releases keep their frozen bytes untouched.
MIGRATE_1_TO_2 = """
ALTER TABLE packets RENAME TO packets_v1;
ALTER TABLE readings RENAME TO readings_v1;
ALTER TABLE decisions RENAME TO decisions_v1;
DROP INDEX IF EXISTS readings_step;
DROP INDEX IF EXISTS decisions_reading;
CREATE TABLE packets (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    round_key TEXT NOT NULL DEFAULT '',
    id TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, accepted_at TEXT NOT NULL,
    round_basis TEXT NOT NULL DEFAULT '', receipt TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (session, round_key, id)
);
CREATE TABLE readings (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    id TEXT NOT NULL, step TEXT NOT NULL, observed_at TEXT NOT NULL, indicated_mg INTEGER NOT NULL,
    origin_round_key TEXT NOT NULL DEFAULT '', origin_packet TEXT NOT NULL,
    PRIMARY KEY (session, id),
    FOREIGN KEY (session, origin_round_key, origin_packet) REFERENCES packets(session, round_key, id)
);
CREATE TABLE packet_rows (
    session TEXT NOT NULL, round_key TEXT NOT NULL, packet TEXT NOT NULL, reading TEXT NOT NULL,
    PRIMARY KEY (session, round_key, packet, reading),
    FOREIGN KEY (session, round_key, packet) REFERENCES packets(session, round_key, id),
    FOREIGN KEY (session, reading) REFERENCES readings(session, id)
);
CREATE TABLE pending_packets (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    receipt TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'retransmission')),
    round_key TEXT NOT NULL DEFAULT '', resolved_at TEXT,
    PRIMARY KEY (session, receipt)
);
CREATE TABLE decisions (
    session TEXT NOT NULL, generation INTEGER NOT NULL, reading TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('exclude', 'include')),
    reason TEXT NOT NULL, made_at TEXT NOT NULL, PRIMARY KEY (session, generation),
    FOREIGN KEY (session, reading) REFERENCES readings(session, id)
);
INSERT INTO packets(session, round_key, id, payload, digest, accepted_at, round_basis, receipt)
    SELECT session, '', id, payload, digest, accepted_at, 'legacy', '' FROM packets_v1;
INSERT INTO readings(session, id, step, observed_at, indicated_mg, origin_round_key, origin_packet)
    SELECT session, id, step, observed_at, indicated_mg, '', origin_packet FROM readings_v1;
INSERT INTO packet_rows(session, round_key, packet, reading)
    SELECT session, '', origin_packet, id FROM readings_v1;
INSERT INTO decisions(session, generation, reading, action, reason, made_at)
    SELECT session, generation, reading, action, reason, made_at FROM decisions_v1;
DROP TABLE decisions_v1;
DROP TABLE readings_v1;
DROP TABLE packets_v1;
CREATE INDEX packets_round ON packets(session, round_key, id);
CREATE INDEX readings_step ON readings(session, step, observed_at);
CREATE INDEX packet_rows_reading ON packet_rows(session, reading);
CREATE INDEX pending_packets_status ON pending_packets(session, status, received_at);
CREATE INDEX decisions_reading ON decisions(session, reading, generation);
"""
