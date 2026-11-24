VERSION = 2

# A reading may legitimately arrive in several packets; every receiving packet is
# a real origin. The map is scoped by session so another session reusing the same
# reading number never leaks in, and the primary key absorbs packet resends.
SOURCES_TABLE = """
CREATE TABLE IF NOT EXISTS reading_sources (
    session TEXT NOT NULL,
    reading TEXT NOT NULL,
    packet TEXT NOT NULL,
    PRIMARY KEY (session, reading, packet),
    FOREIGN KEY (session, reading) REFERENCES readings(session, id),
    FOREIGN KEY (session, packet) REFERENCES packets(session, id)
)
"""

SOURCES_INDEX = "CREATE INDEX IF NOT EXISTS reading_sources_packet ON reading_sources(session, packet)"

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
""" + SOURCES_TABLE + ";\n" + SOURCES_INDEX + """;

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
