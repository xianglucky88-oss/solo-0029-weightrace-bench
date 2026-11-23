from contextlib import contextmanager
from pathlib import Path
import sqlite3

from .schema import MIGRATIONS, SCHEMA, VERSION


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > VERSION:
                raise ValueError(f"无法打开数据库结构版本 {version}")
            if version == 0:
                connection.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA}\nPRAGMA user_version = {VERSION};\nCOMMIT;")
            else:
                for step in range(version, VERSION):
                    connection.executescript(
                        f"BEGIN IMMEDIATE;\n{MIGRATIONS[step]}\nPRAGMA user_version = {step + 1};\nCOMMIT;")
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
