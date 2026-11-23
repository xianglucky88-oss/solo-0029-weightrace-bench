from contextlib import contextmanager
from pathlib import Path
import sqlite3

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
            if version == 0:
                connection.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA}\nPRAGMA user_version = {VERSION};\nCOMMIT;")
            elif version < VERSION:
                # Upgrade in place.  Packets and readings gain round provenance;
                # releases and withdrawals are never rewritten, so already
                # published files keep their bytes and stay replayable.
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{MIGRATE_1_TO_2}\nPRAGMA user_version = {VERSION};\nCOMMIT;")
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
