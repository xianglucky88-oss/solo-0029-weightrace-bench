from contextlib import contextmanager
from pathlib import Path
import sqlite3

from .codec import canonical, loads
from .schema import MIGRATE_1_TO_2, SCHEMA, VERSION


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, VERSION):
                raise ValueError(f"无法打开数据库结构版本 {version}")
            if version in (0, 1):
                connection.execute("BEGIN IMMEDIATE")
                if version == 0:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                else:
                    for statement in MIGRATE_1_TO_2.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    for sid, document in connection.execute("SELECT id, plan FROM sessions"):
                        plan = loads(document)
                        connection.execute(
                            "INSERT INTO rounds(session, round, high_load, origin, switched_at) VALUES (?, 0, ?, 'plan', ?)",
                            (sid, canonical(plan["loads"]["high"]), plan["measured_on"] + "T00:00:00Z"))
                connection.execute(f"PRAGMA user_version = {VERSION}")
                connection.execute("COMMIT")
            connection.execute("PRAGMA journal_mode = WAL")
        finally:
            connection.close()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def transaction(self, write=False):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
