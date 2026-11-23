VERSION = 2

ADOPTIONS = """
CREATE TABLE IF NOT EXISTS adoptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    metric TEXT NOT NULL CHECK (metric IN ('indication', 'hysteresis', 'repeatability', 'eccentricity', 'drift')),
    release INTEGER NOT NULL,
    reason TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    superseded_at TEXT,
    supersede_reason TEXT,
    FOREIGN KEY (session, release) REFERENCES releases(session, number)
);
CREATE UNIQUE INDEX IF NOT EXISTS adoptions_active ON adoptions(session, metric) WHERE superseded_at IS NULL;
"""

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
""" + ADOPTIONS

MIGRATIONS = {1: ADOPTIONS}
