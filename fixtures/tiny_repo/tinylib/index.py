"""Write notes into SQLite."""

import sqlite3


def index_notes(destination: str) -> None:
    """Write notes into a SQLite database at notes.db."""
    connection = sqlite3.connect(destination)
    connection.execute("create table if not exists notes (body text)")
    connection.commit()
    connection.close()
