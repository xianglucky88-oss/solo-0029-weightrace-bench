VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS standards (
    id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
    PRIMARY KEY (id, revision)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, plan TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bulletins (
    id TEXT PRIMARY KEY, document TEXT NOT NULL, digest TEXT NOT NULL,
    seq INTEGER NOT NULL, published_at TEXT NOT NULL
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
    digest TEXT NOT NULL, bundle TEXT NOT NULL, basis_id TEXT,
    PRIMARY KEY (session, number), UNIQUE (session, generation, basis_id)
);
CREATE TABLE IF NOT EXISTS withdrawals (
    session TEXT NOT NULL, number INTEGER NOT NULL, reason TEXT NOT NULL, withdrawn_at TEXT NOT NULL,
    PRIMARY KEY (session, number), FOREIGN KEY (session, number) REFERENCES releases(session, number)
);
"""

MIGRATE_1_2 = """
PRAGMA foreign_keys=OFF;
CREATE TABLE releases_v2 (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    number INTEGER NOT NULL, generation INTEGER NOT NULL, published_at TEXT NOT NULL,
    digest TEXT NOT NULL, bundle TEXT NOT NULL, basis_id TEXT,
    PRIMARY KEY (session, number), UNIQUE (session, generation, basis_id)
);
INSERT INTO releases_v2(session, number, generation, published_at, digest, bundle, basis_id)
SELECT session, number, generation, published_at, digest, bundle, NULL FROM releases;
DROP TABLE releases;
ALTER TABLE releases_v2 RENAME TO releases;
CREATE TABLE bulletins (
    id TEXT PRIMARY KEY, document TEXT NOT NULL, digest TEXT NOT NULL,
    seq INTEGER NOT NULL, published_at TEXT NOT NULL
);
PRAGMA foreign_keys=ON;
"""
