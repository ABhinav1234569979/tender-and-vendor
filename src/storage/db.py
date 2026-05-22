import sqlite3


def get_connection(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def init_db(db_path: str) -> None:
    with get_connection(db_path) as conn:
        with open("src/storage/schema.sql", "r", encoding="utf-8") as f:
            conn.executescript(f.read())
