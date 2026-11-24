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
    id TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, accepted_at TEXT NOT NULL,
    PRIMARY KEY (session, id)
);
CREATE TABLE IF NOT EXISTS readings (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    id TEXT NOT NULL, step TEXT NOT NULL, observed_at TEXT NOT NULL, indicated_mg INTEGER NOT NULL,
    origin_packet TEXT NOT NULL, PRIMARY KEY (session, id),
    FOREIGN KEY (session, origin_packet) REFERENCES packets(session, id)
);
CREATE INDEX IF NOT EXISTS readings_step ON readings(session, step, observed_at);
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
CREATE TABLE IF NOT EXISTS handoffs (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    number INTEGER NOT NULL, generation INTEGER NOT NULL, plan_digest TEXT NOT NULL,
    confirmed_at TEXT NOT NULL, reviewer TEXT NOT NULL,
    zero_in TEXT NOT NULL, rise_low TEXT NOT NULL, rise_high TEXT NOT NULL, zero_mid_before TEXT NOT NULL,
    digest TEXT NOT NULL, document TEXT NOT NULL,
    PRIMARY KEY (session, number),
    FOREIGN KEY (session, zero_in) REFERENCES readings(session, id),
    FOREIGN KEY (session, rise_low) REFERENCES readings(session, id),
    FOREIGN KEY (session, rise_high) REFERENCES readings(session, id),
    FOREIGN KEY (session, zero_mid_before) REFERENCES readings(session, id)
);
CREATE INDEX IF NOT EXISTS handoffs_generation ON handoffs(session, generation);
-- Invalidation is an append-only history: the same hand-off can lapse more than
-- once (e.g. after a re-confirm), and every event stays queryable.
CREATE TABLE IF NOT EXISTS invalidations (
    session TEXT NOT NULL, number INTEGER NOT NULL, event INTEGER NOT NULL, generation INTEGER NOT NULL,
    reason TEXT NOT NULL, detail TEXT NOT NULL, invalidated_at TEXT NOT NULL,
    PRIMARY KEY (session, number, event),
    FOREIGN KEY (session, number) REFERENCES handoffs(session, number)
);
"""

# v1 -> v2 introduced the segmented session flag and the hand-off registers.
# Everything below is additive, so a v1 work database upgrades in place without
# touching standards, sessions, packets, readings, decisions or releases.
MIGRATION_2 = """
CREATE TABLE IF NOT EXISTS handoffs (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    number INTEGER NOT NULL, generation INTEGER NOT NULL, plan_digest TEXT NOT NULL,
    confirmed_at TEXT NOT NULL, reviewer TEXT NOT NULL,
    zero_in TEXT NOT NULL, rise_low TEXT NOT NULL, rise_high TEXT NOT NULL, zero_mid_before TEXT NOT NULL,
    digest TEXT NOT NULL, document TEXT NOT NULL,
    PRIMARY KEY (session, number),
    FOREIGN KEY (session, zero_in) REFERENCES readings(session, id),
    FOREIGN KEY (session, rise_low) REFERENCES readings(session, id),
    FOREIGN KEY (session, rise_high) REFERENCES readings(session, id),
    FOREIGN KEY (session, zero_mid_before) REFERENCES readings(session, id)
);
CREATE INDEX IF NOT EXISTS handoffs_generation ON handoffs(session, generation);
CREATE TABLE IF NOT EXISTS invalidations (
    session TEXT NOT NULL, number INTEGER NOT NULL, event INTEGER NOT NULL, generation INTEGER NOT NULL,
    reason TEXT NOT NULL, detail TEXT NOT NULL, invalidated_at TEXT NOT NULL,
    PRIMARY KEY (session, number, event),
    FOREIGN KEY (session, number) REFERENCES handoffs(session, number)
);
"""
